"""Evaluate the presealed sign-only OFZ curve governor for frozen V49 NAV."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v52_ofz_carry_roll_down as v52
from market_lab.futures import moex_stock_futures_cash_carry_source as artifact_io
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v53_ofz_curve_v49_governor_v1.yaml"
CONFIG_SHA256: Final[str] = "838ee791d6105161c8c19c1b6211f0c53fd38d53c93555de9589c0a3b8959227"
SCENARIOS: Final[tuple[str, ...]] = ("primary", "doubled", "stress", "execution_stress")


def _sha(path: Path) -> str:
    return artifact_io.sha256_file(path)


def _safe_root(value: str, expected: str) -> Path:
    relative = Path(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or relative.parts[0].lower() != expected
    ):
        raise ValueError("unsafe V53 root")
    return PROJECT_ROOT / relative


def load_protocol() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V53 config must be an object")
    curve, governor, gates = payload["curve_state"], payload["governor"], payload["gates"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "v53_ofz_curve_v49_governor_v1"
        or payload.get("status") != "sealed_before_any_ofz_curve_state_or_v49_join"
        or payload.get("normalized_development_proxy") is not True
        or payload.get("live_trading_allowed") is not False
        or curve["history_currency_id"] != "SUR"
        or float(curve["minimum_trailing_median_value_rub"]) != 10_000_000.0
        or curve["threshold_or_bucket_search"] != "forbidden"
        or int(curve["minimum_securities_per_bucket"]) != 2
        or float(governor["inverted_factor"]) != 1.25
        or float(governor["normal_factor"]) != 0.75
        or float(governor["missing_factor"]) != 0.0
        or governor["factor_sign_or_magnitude_search"] != "forbidden"
        or gates["exact_replay_required_before_forward"] is not True
        or gates["live_promotion_forbidden"] is not True
    ):
        raise ValueError("V53 protocol drifted")
    ofz, v49 = payload["inputs"]["ofz_source"], payload["inputs"]["frozen_v49"]
    roots = {"ofz": _safe_root(ofz["root"], "data"), "v49": _safe_root(v49["root"], "runs")}
    for root, declarations in (
        (roots["ofz"], (ofz["manifest"], ofz["audit"], ofz["history"])),
        (roots["v49"], (v49["manifest"], v49["ledger"])),
    ):
        for item in declarations:
            path = root / item["file"]
            if _sha(path) != item["sha256"]:
                raise ValueError(f"V53 input drifted: {path.name}")
            if "rows" in item and pq.ParquetFile(path).metadata.num_rows != int(item["rows"]):
                raise ValueError(f"V53 input rows drifted: {path.name}")
    source_manifest = json.loads(
        (roots["ofz"] / ofz["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    source_audit = json.loads(
        (roots["ofz"] / ofz["audit"]["file"]).read_text(encoding="utf-8-sig")
    )
    v49_manifest = json.loads(
        (roots["v49"] / v49["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    if (
        source_manifest.get("config_sha256") != ofz["protocol_sha256"]
        or source_audit.get("all_true") is not True
        or v49_manifest.get("protocol_sha256") != v49["protocol_sha256"]
    ):
        raise ValueError("V53 parent identity drifted")
    payload["_config_sha256"] = actual
    payload["_ofz_root"] = roots["ofz"]
    payload["_v49_root"] = roots["v49"]
    return payload


def build_curve_states(history: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    curve = config["curve_state"]
    frame = history.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    frame["maturity_date"] = pd.to_datetime(frame["maturity_date"]).dt.normalize()
    frame["available_at_utc"] = pd.to_datetime(frame["available_at_utc"], utc=True)
    for column in ("value_rub", "yield_at_wap_pct"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.sort_values(["security_id", "trade_date"], kind="mergesort")
    window = int(curve["trailing_liquidity_observations"])
    frame["trailing_median_value_rub"] = frame.groupby("security_id", sort=False)[
        "value_rub"
    ].transform(lambda values: values.rolling(window, min_periods=window).median())
    month_last = frame.groupby(frame["trade_date"].dt.to_period("M"))["trade_date"].max()
    rows: list[dict[str, Any]] = []
    short = curve["short_bucket_years"]
    long = curve["long_bucket_years"]
    minimum = int(curve["minimum_securities_per_bucket"])
    for decision_date in month_last:
        current = frame.loc[frame["trade_date"].eq(decision_date)].copy()
        remaining = (current["maturity_date"] - decision_date).dt.days / 365.25
        common = (
            current["security_id"].astype(str).str.startswith(curve["universe_security_id_prefix"])
            & current["currency_id"].astype(str).eq(curve["history_currency_id"])
            & current["face_unit"].astype(str).eq(curve["face_unit"])
            & current["trailing_median_value_rub"].ge(
                float(curve["minimum_trailing_median_value_rub"])
            )
            & current["yield_at_wap_pct"].gt(0)
        )
        short_values = current.loc[
            common
            & remaining.ge(float(short["minimum_inclusive"]))
            & remaining.lt(float(short["maximum_exclusive"])),
            "yield_at_wap_pct",
        ]
        long_values = current.loc[
            common
            & remaining.ge(float(long["minimum_inclusive"]))
            & remaining.le(float(long["maximum_inclusive"])),
            "yield_at_wap_pct",
        ]
        valid = len(short_values) >= minimum and len(long_values) >= minimum
        short_median = float(short_values.median()) if valid else np.nan
        long_median = float(long_values.median()) if valid else np.nan
        slope = long_median - short_median if valid else np.nan
        state = "inverted" if valid and slope <= 0 else "normal" if valid else "missing"
        factor = 1.25 if state == "inverted" else 0.75 if state == "normal" else 0.0
        availability = current.loc[common, "available_at_utc"].max() if common.any() else pd.NaT
        effective_date = (
            availability.tz_convert("Europe/Moscow").tz_localize(None).normalize()
            if pd.notna(availability)
            else pd.NaT
        )
        rows.append(
            {
                "decision_date": decision_date,
                "available_at_utc": availability,
                "effective_date": effective_date,
                "short_count": len(short_values),
                "long_count": len(long_values),
                "short_median_yield_pct": short_median,
                "long_median_yield_pct": long_median,
                "slope_pct_points": slope,
                "curve_state": state,
                "risk_factor": factor,
            }
        )
    return pd.DataFrame(rows)


def apply_governor(states: pd.DataFrame, v49: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    base = v49.copy()
    base["date"] = pd.to_datetime(base.pop("session_date")).dt.normalize()
    start, end = pd.Timestamp(config["dates"]["start"]), pd.Timestamp(config["dates"]["end"])
    base = base.loc[base["date"].between(start, end)].sort_values("date")
    valid_states = states.loc[states["effective_date"].notna()].sort_values("effective_date")
    joined = pd.merge_asof(
        base.loc[:, ["date"]],
        valid_states.loc[:, ["effective_date", "decision_date", "curve_state", "risk_factor"]],
        left_on="date",
        right_on="effective_date",
        direction="backward",
        allow_exact_matches=True,
    )
    joined["curve_state"] = joined["curve_state"].fillna("missing")
    joined["risk_factor"] = joined["risk_factor"].fillna(0.0)
    outputs: list[pd.DataFrame] = []
    for scenario, column in config["scenario_columns"].items():
        nav = pd.to_numeric(base[column], errors="raise")
        parent_return = nav.pct_change().fillna(0.0)
        governed_return = joined["risk_factor"] * parent_return.to_numpy()
        governed_nav = (1.0 + governed_return).cumprod()
        item = joined.copy()
        item["scenario"] = scenario
        item["parent_return"] = parent_return.to_numpy()
        item["governed_return"] = governed_return
        item["governed_nav"] = governed_nav
        outputs.append(item)
    return pd.concat(outputs, ignore_index=True)


def evaluate(config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    ofz = config["inputs"]["ofz_source"]
    v49_input = config["inputs"]["frozen_v49"]
    history = pd.read_parquet(config["_ofz_root"] / ofz["history"]["file"])
    protected = pd.Timestamp(config["dates"]["protected_from"])
    if pd.to_datetime(history["trade_date"]).ge(protected).any():
        raise ValueError("V53 OFZ history crossed protected period")
    states = build_curve_states(history, config)
    v49 = pd.read_parquet(config["_v49_root"] / v49_input["ledger"]["file"])
    ledger = apply_governor(states, v49, config)
    scenario_metrics = {
        scenario: v52.metrics(group["governed_nav"], group["date"])
        for scenario, group in ledger.groupby("scenario", sort=False)
    }
    state_counts = states["curve_state"].value_counts().to_dict()
    covered = ledger.loc[ledger["scenario"].eq("primary"), "curve_state"].ne("missing").mean()
    gates = config["gates"]
    checks = {
        "zero_protected_rows": True,
        "zero_same_session_lookahead": bool(
            states.dropna(subset=["effective_date"])["effective_date"].gt(
                states.dropna(subset=["effective_date"])["decision_date"]
            ).all()
        ),
        "minimum_valid_state_months": int(states["curve_state"].ne("missing").sum())
        >= int(gates["minimum_valid_state_months"]),
        "both_curve_states_observed": state_counts.get("normal", 0) > 0
        and state_counts.get("inverted", 0) > 0,
        "minimum_state_covered_V49_session_fraction": bool(
            covered >= float(gates["minimum_state_covered_V49_session_fraction"])
        ),
        "all_nav_positive": all(
            group["governed_nav"].gt(0).all() for _, group in ledger.groupby("scenario")
        ),
        "primary_cagr": scenario_metrics["primary"]["cagr"]
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
        "primary_positive_years": scenario_metrics["primary"]["positive_years"]
        >= int(gates["primary_positive_years_gte"]),
        "aspirational_primary_cagr_50": scenario_metrics["primary"]["cagr"]
        >= float(gates["aspirational_primary_cagr_gte"]),
    }
    required = {key: value for key, value in checks.items() if not key.startswith("aspirational_")}
    summary = {
        "protocol_sha256": config["_config_sha256"],
        "state_counts": state_counts,
        "valid_state_months": int(states["curve_state"].ne("missing").sum()),
        "state_covered_V49_session_fraction": float(covered),
        "metrics": scenario_metrics,
        "gates": checks,
        "verdict": "GO_TO_EXACT_REPLAY" if all(required.values()) else "NO_GO",
        "live_trading_allowed": False,
    }
    return states, ledger, summary


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as stream:
        path = Path(stream.name)
    try:
        frame.to_parquet(path, index=False)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"file": path.name, "bytes": path.stat().st_size, "sha256": _sha(path)}
    if rows is not None:
        item["rows"] = rows
    return item


def audit_run(config: dict[str, Any], output: Path, rebuild: bool = True) -> dict[str, Any]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    checks = {
        "protocol_exact": manifest["protocol_sha256"] == config["_config_sha256"],
        "implementation_exact": manifest["implementation_sha256"] == _sha(Path(__file__)),
        "manifest_sidecar_exact": (
            (output / "manifest.sha256").read_text(encoding="utf-8-sig").split()[0]
            == _sha(output / "manifest.json")
        ),
        "live_false": manifest["live_trading_allowed"] is False,
    }
    for name, item in manifest["artifacts"].items():
        path = output / item["file"]
        checks[f"{name}_exact"] = path.exists() and _sha(path) == item["sha256"]
    if rebuild:
        states, ledger, summary = evaluate(config)
        for name, expected in (("curve_states", states), ("governed_ledger", ledger)):
            try:
                pd.testing.assert_frame_equal(
                    pd.read_parquet(output / f"{name}.parquet"),
                    expected,
                    check_dtype=False,
                )
                checks[f"{name}_replay_exact"] = True
            except AssertionError:
                checks[f"{name}_replay_exact"] = False
        stored = json.loads(
            (output / "metrics.json").read_text(encoding="utf-8-sig")
        )
        checks["metrics_replay_exact"] = stored == summary
    return {"checks": checks, "all_true": all(checks.values())}


def run(config: dict[str, Any]) -> Path:
    states, ledger, summary = evaluate(config)
    created = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = _safe_root(config["outputs"]["root"], "runs")
    output = root.parent / f"{root.name}_{created}_{config['_config_sha256'][:8]}"
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_bytes(output / "curve_states.parquet", _parquet_bytes(states))
    atomic_write_bytes(output / "governed_ledger.parquet", _parquet_bytes(ledger))
    write_json(output / "metrics.json", summary)
    atomic_write_text(
        output / "report.md",
        f"# V53 OFZ curve governor\n\nVerdict: `{summary['verdict']}`. "
        "Live trading: `false`.\n",
    )
    artifacts = {
        "curve_states": _artifact(output / "curve_states.parquet", len(states)),
        "governed_ledger": _artifact(output / "governed_ledger.parquet", len(ledger)),
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
        output / "manifest.sha256",
        f"{_sha(output / 'manifest.json')}  manifest.json\n",
    )
    write_json(output / "audit.json", audit_run(config, output, rebuild=True))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    config = load_protocol()
    if args.audit:
        audit = audit_run(config, args.audit, rebuild=True)
        print(json.dumps(audit, indent=2, sort_keys=True))
        raise SystemExit(0 if audit["all_true"] else 1)
    output = run(config)
    summary = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8-sig"))
    print(f"run={output.name}")
    print(f"verdict={summary['verdict']}")
    print(f"audit_all_true={audit['all_true']}")


if __name__ == "__main__":
    main()


__all__ = ["CONFIG_PATH", "CONFIG_SHA256", "apply_governor", "build_curve_states", "load_protocol"]
