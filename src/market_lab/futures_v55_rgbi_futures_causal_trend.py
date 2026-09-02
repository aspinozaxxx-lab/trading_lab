"""Run the sealed V55 normalized causal RGBI futures trend candidate."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v52_ofz_carry_roll_down as metrics_engine
from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v55_rgbi_futures_causal_trend_v1.yaml"
CONFIG_SHA256: Final[str] = "6f27813b5cc3d30dc667468e4855a4cfb618291476677f9f373e2d018819bbe2"
SCENARIOS: Final[tuple[str, ...]] = ("primary_5bps", "doubled_10bps", "stress_20bps")


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def _root(value: str, expected: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("unsafe V55 path")
    if relative.parts[0].lower() != expected:
        raise ValueError("V55 path escaped declared root")
    return PROJECT_ROOT / relative


def load_protocol() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V55 config must be an object")
    candidate, execution, gates = payload["candidate"], payload["execution"], payload["gates"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "v55_rgbi_futures_causal_trend_v1"
        or payload.get("status")
        != "sealed_before_any_RGBI_market_value_return_signal_trade_or_pnl"
        or payload.get("independent_return_engine") is not True
        or payload.get("live_trading_allowed") is not False
        or int(candidate["momentum_sessions"]) != 63
        or int(candidate["volatility_sessions"]) != 20
        or float(candidate["annual_volatility_target"]) != 0.25
        or float(candidate["maximum_absolute_target"]) != 3.0
        or int(candidate["roll_days_before_expiration"]) != 10
        or execution["fractional_notional_proxy"] is not True
        or tuple(float(x["one_way_bps"]) for x in payload["cost_scenarios"].values())
        != (5.0, 10.0, 20.0)
        or gates["exact_replay_required_before_forward"] is not True
        or gates["live_promotion_forbidden"] is not True
    ):
        raise ValueError("V55 protocol drifted")
    source = payload["input"]
    root = _root(source["root"], "data")
    for item in (
        source["manifest"],
        source["audit"],
        source["series"],
        source["daily"],
        source["raw"],
    ):
        path = root / item["file"]
        if _sha(path) != item["sha256"]:
            raise ValueError(f"V55 source drifted: {path.name}")
        if (
            "rows" in item
            and path.suffix == ".parquet"
            and pq.ParquetFile(path).metadata.num_rows != int(item["rows"])
        ):
            raise ValueError(f"V55 source rows drifted: {path.name}")
    manifest = json.loads((root / source["manifest"]["file"]).read_text(encoding="utf-8-sig"))
    audit = json.loads((root / source["audit"]["file"]).read_text(encoding="utf-8-sig"))
    if (
        manifest.get("protocol_sha256") != source["source_protocol_sha256"]
        or manifest.get("source_only") is not True
        or manifest.get("contains_curve_return_label_signal_trade_or_pnl") is not False
        or audit.get("all_true") is not True
    ):
        raise ValueError("V55 source identity or audit drifted")
    payload["_config_sha256"] = actual
    payload["_source_root"] = root
    return payload


def build_continuous_state(
    series: pd.DataFrame, daily: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    candidate = config["candidate"]
    contracts = series.copy()
    contracts["start_date"] = pd.to_datetime(contracts["start_date"]).dt.normalize()
    contracts["expiration_date"] = pd.to_datetime(contracts["expiration_date"]).dt.normalize()
    history = daily.copy()
    history["trade_date"] = pd.to_datetime(history["trade_date"]).dt.normalize()
    for column in ("open", "settle_price", "volume", "num_trades"):
        history[column] = pd.to_numeric(history[column], errors="coerce")
    history = history.sort_values(["secid", "trade_date"], kind="mergesort")
    lookup = {
        (pd.Timestamp(row.trade_date), str(row.secid)): row._asdict()
        for row in history.itertuples(index=False)
    }
    dates = sorted(history["trade_date"].unique())
    rows: list[dict[str, Any]] = []
    previous_date: pd.Timestamp | None = None
    previous_contract: str | None = None
    for raw_date in dates:
        date = pd.Timestamp(raw_date)
        eligible = contracts.loc[
            contracts["start_date"].le(date)
            & contracts["expiration_date"].sub(date).dt.days.ge(
                int(candidate["roll_days_before_expiration"])
            )
        ].sort_values("expiration_date")
        active = str(eligible.iloc[0]["secid"]) if not eligible.empty else None
        current = lookup.get((date, active)) if active is not None else None
        adjusted_return = np.nan
        roll_overlap = True
        if current is not None and previous_date is not None and previous_contract is not None:
            if active == previous_contract:
                prior = lookup.get((previous_date, active))
            else:
                prior = lookup.get((previous_date, active))
                roll_overlap = prior is not None
            if (
                prior is not None
                and float(prior["settle_price"]) > 0
                and float(current["settle_price"]) > 0
            ):
                adjusted_return = math.log(
                    float(current["settle_price"]) / float(prior["settle_price"])
                )
        rows.append(
            {
                "date": date,
                "active_secid": active,
                "settle_price": float(current["settle_price"]) if current is not None else np.nan,
                "adjusted_log_return": adjusted_return,
                "contract_changed": previous_contract is not None and active != previous_contract,
                "roll_overlap_complete": roll_overlap,
            }
        )
        previous_date, previous_contract = date, active
    output = pd.DataFrame(rows)
    momentum_window = int(candidate["momentum_sessions"])
    volatility_window = int(candidate["volatility_sessions"])
    returns = output["adjusted_log_return"]
    momentum_count = returns.rolling(momentum_window).count()
    volatility_count = returns.rolling(volatility_window).count()
    output["momentum"] = returns.rolling(momentum_window).sum().where(
        momentum_count.eq(momentum_window)
    )
    output["annualized_volatility"] = (
        returns.rolling(volatility_window).std(ddof=1) * math.sqrt(252.0)
    ).where(volatility_count.eq(volatility_window))
    direction = np.sign(output["momentum"])
    raw_target = float(candidate["annual_volatility_target"]) / output[
        "annualized_volatility"
    ].where(output["annualized_volatility"].gt(0))
    output["target"] = direction * raw_target.clip(
        upper=float(candidate["maximum_absolute_target"])
    )
    output.loc[output["momentum"].eq(0), "target"] = 0.0
    return output


def build_decisions_and_ledger(
    state: pd.DataFrame, daily: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    history = daily.copy().sort_values(["secid", "trade_date"], kind="mergesort")
    history["trade_date"] = pd.to_datetime(history["trade_date"]).dt.normalize()
    for column in ("open", "volume", "num_trades"):
        history[column] = pd.to_numeric(history[column], errors="coerce")
    history["next_open"] = history.groupby("secid", sort=False)["open"].shift(-1)
    history["next_date"] = history.groupby("secid", sort=False)["trade_date"].shift(-1)
    lookup = {
        (pd.Timestamp(row.trade_date), str(row.secid)): row._asdict()
        for row in history.itertuples(index=False)
    }
    shifted = state.loc[:, ["date", "target"]].copy()
    shifted["decision_date"] = shifted["date"]
    target_by_execution = shifted.set_index("date")["target"].shift(1)
    decisions: list[dict[str, Any]] = []
    raw_periods: list[dict[str, Any]] = []
    previous_target = 0.0
    previous_contract: str | None = None
    unresolved = 0
    for row in state.itertuples(index=False):
        execution_date = pd.Timestamp(row.date)
        target = target_by_execution.get(execution_date, np.nan)
        decision_date = state.loc[state["date"].lt(execution_date), "date"].max()
        if pd.isna(target) or row.active_secid is None:
            continue
        market = lookup.get((execution_date, str(row.active_secid)))
        executable = bool(
            market is not None
            and float(market["open"]) > 0
            and float(market["next_open"]) > 0
            and float(market["volume"]) > 0
            and float(market["num_trades"]) > 0
            and pd.notna(market["next_date"])
        )
        decisions.append(
            {
                "decision_date": decision_date,
                "execution_date": execution_date,
                "secid": row.active_secid,
                "target": target,
                "executable": executable,
            }
        )
        if not executable:
            unresolved += 1
            continue
        contract_changed = previous_contract is not None and row.active_secid != previous_contract
        turnover = (
            abs(previous_target) + abs(float(target))
            if contract_changed
            else abs(float(target) - previous_target)
        )
        gross_return = float(target) * (
            float(market["next_open"]) / float(market["open"]) - 1.0
        )
        raw_periods.append(
            {
                "decision_date": decision_date,
                "execution_date": execution_date,
                "exit_date": pd.Timestamp(market["next_date"]),
                "secid": row.active_secid,
                "target": float(target),
                "turnover": turnover,
                "gross_return": gross_return,
                "contract_changed": contract_changed,
            }
        )
        previous_target, previous_contract = float(target), str(row.active_secid)
    period = pd.DataFrame(raw_periods)
    ledgers = []
    for scenario in SCENARIOS:
        cost_rate = float(config["cost_scenarios"][scenario]["one_way_bps"]) / 10_000.0
        item = period.copy()
        item["scenario"] = scenario
        item["cost_return"] = item["turnover"] * cost_rate
        item["net_return"] = item["gross_return"] - item["cost_return"]
        item["nav"] = (1.0 + item["net_return"]).cumprod()
        ledgers.append(item)
    return pd.DataFrame(decisions), pd.concat(ledgers, ignore_index=True), {
        "unresolved": unresolved,
        "candidate_sessions": len(decisions),
        "executed_sessions": len(period),
    }


def evaluate(
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    source = config["input"]
    series = pd.read_parquet(config["_source_root"] / source["series"]["file"])
    daily = pd.read_parquet(config["_source_root"] / source["daily"]["file"])
    if pd.to_datetime(daily["trade_date"]).ge(config["dates"]["protected_from"]).any():
        raise ValueError("V55 protected rows detected")
    state = build_continuous_state(series, daily, config)
    decisions, ledger, counts = build_decisions_and_ledger(state, daily, config)
    scenario_metrics = {
        name: metrics_engine.metrics(group["nav"], group["exit_date"])
        for name, group in ledger.groupby("scenario", sort=False)
    }
    gates = config["gates"]
    unresolved_fraction = counts["unresolved"] / max(counts["candidate_sessions"], 1)
    checks = {
        "zero_protected_rows": True,
        "zero_same_session_signal_execution": bool(
            decisions["execution_date"].gt(decisions["decision_date"]).all()
        ),
        "zero_roll_gap_imputation": bool(
            state.loc[state["contract_changed"], "roll_overlap_complete"].all()
        ),
        "minimum_signal_sessions": int(state["target"].notna().sum())
        >= int(gates["minimum_signal_sessions"]),
        "minimum_executed_sessions": counts["executed_sessions"]
        >= int(gates["minimum_executed_sessions"]),
        "maximum_unresolved_execution_fraction": unresolved_fraction
        <= float(gates["maximum_unresolved_execution_fraction"]),
        "all_nav_positive": bool(ledger["nav"].gt(0).all()),
        "primary_cagr": scenario_metrics["primary_5bps"]["cagr"]
        >= float(gates["primary_cagr_gte"]),
        "all_scenario_cagr": all(
            item["cagr"] >= float(gates["all_scenario_cagr_gte"])
            for item in scenario_metrics.values()
        ),
        "all_scenario_sharpe": all(
            item["sharpe"] >= float(gates["all_scenario_sharpe_gte"])
            for item in scenario_metrics.values()
        ),
        "all_scenario_mdd": all(
            item["maximum_drawdown"] <= float(gates["all_scenario_mdd_lte"])
            for item in scenario_metrics.values()
        ),
        "all_scenario_worst_year": all(
            item["worst_year"] >= float(gates["all_scenario_worst_year_gte"])
            for item in scenario_metrics.values()
        ),
        "primary_positive_years": scenario_metrics["primary_5bps"]["positive_years"]
        >= int(gates["primary_positive_years_gte"]),
        "aspirational_primary_cagr_50": scenario_metrics["primary_5bps"]["cagr"]
        >= float(gates["aspirational_primary_cagr_gte"]),
    }
    required = {k: v for k, v in checks.items() if not k.startswith("aspirational_")}
    summary = {
        "protocol_sha256": config["_config_sha256"],
        "counts": counts | {"signal_sessions": int(state["target"].notna().sum())},
        "unresolved_fraction": unresolved_fraction,
        "metrics": scenario_metrics,
        "gates": checks,
        "verdict": "GO_TO_EXACT_REPLAY" if all(required.values()) else "NO_GO",
        "live_trading_allowed": False,
    }
    return state, decisions, ledger, summary


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as stream:
        path = Path(stream.name)
    try:
        frame.to_parquet(path, index=False)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"file": path.name, "bytes": path.stat().st_size, "sha256": _sha(path)}
    if rows is not None:
        value["rows"] = rows
    return value


def audit_run(config: dict[str, Any], output: Path, rebuild: bool = True) -> dict[str, Any]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    checks = {
        "protocol_exact": manifest["protocol_sha256"] == config["_config_sha256"],
        "implementation_exact": manifest["implementation_sha256"] == _sha(Path(__file__)),
        "manifest_sidecar_exact": (output / "manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        == _sha(output / "manifest.json"),
        "live_false": manifest["live_trading_allowed"] is False,
    }
    for name, item in manifest["artifacts"].items():
        path = output / item["file"]
        checks[f"{name}_exact"] = path.exists() and _sha(path) == item["sha256"]
    if rebuild:
        rebuilt = evaluate(config)
        for name, expected in zip(
            ("continuous_state", "decisions", "scenario_ledger"), rebuilt[:3], strict=True
        ):
            try:
                pd.testing.assert_frame_equal(
                    pd.read_parquet(output / f"{name}.parquet"), expected, check_dtype=False
                )
                checks[f"{name}_replay_exact"] = True
            except AssertionError:
                checks[f"{name}_replay_exact"] = False
        checks["metrics_replay_exact"] = json.loads(
            (output / "metrics.json").read_text(encoding="utf-8-sig")
        ) == rebuilt[3]
    return {"checks": checks, "all_true": all(checks.values())}


def run(config: dict[str, Any]) -> Path:
    state, decisions, ledger, summary = evaluate(config)
    root = _root(config["outputs"]["root"], "runs")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = root.parent / f"{root.name}_{stamp}_{config['_config_sha256'][:8]}"
    output.mkdir(parents=True, exist_ok=False)
    frames = {"continuous_state": state, "decisions": decisions, "scenario_ledger": ledger}
    for name, frame in frames.items():
        atomic_write_bytes(output / f"{name}.parquet", _parquet_bytes(frame))
    write_json(output / "metrics.json", summary)
    atomic_write_text(
        output / "report.md",
        f"# V55 RGBI causal trend\n\nVerdict: `{summary['verdict']}`. Live: `false`.\n",
    )
    artifacts = {
        **{
            name: _artifact(output / f"{name}.parquet", len(frame))
            for name, frame in frames.items()
        },
        "metrics": _artifact(output / "metrics.json"),
        "report": _artifact(output / "report.md"),
    }
    manifest = {
        "run_id": output.name,
        "protocol_sha256": config["_config_sha256"],
        "implementation_sha256": _sha(Path(__file__)),
        "verdict": summary["verdict"],
        "live_trading_allowed": False,
        "artifacts": artifacts,
    }
    write_json(output / "manifest.json", manifest)
    atomic_write_text(
        output / "manifest.sha256", f"{_sha(output / 'manifest.json')}  manifest.json\n"
    )
    write_json(output / "audit.json", audit_run(config, output, True))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    config = load_protocol()
    if args.audit:
        audit = audit_run(config, args.audit, True)
        print(json.dumps(audit, indent=2, sort_keys=True))
        raise SystemExit(0 if audit["all_true"] else 1)
    output = run(config)
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8-sig"))
    print(f"run={output.name}")
    print(f"verdict={metrics['verdict']}")
    print(f"audit_all_true={audit['all_true']}")


if __name__ == "__main__":
    main()


__all__ = ["CONFIG_PATH", "CONFIG_SHA256", "build_continuous_state", "load_protocol"]
