"""Correct V42 initial switching charge without changing its economics."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow.parquet as pq
import yaml

import market_lab.futures_v42r1_v41_idle_fund_cost_stress as engine
from market_lab.io_utils import atomic_write_bytes, write_json

CONFIG_PATH: Final[Path] = (
    engine.PROJECT_ROOT / "configs/v42r2_v41_idle_fund_cost_stress_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "02a61505067ce73f8475148d5b8906b475859889f5adcfa54309f82b401ad54f"
)


def load_protocol() -> engine.Protocol:
    actual = engine._sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V42R2 config must be an object")
    frozen = payload["frozen_inheritance"]
    correction = payload["correction"]
    switching = payload["switching_accounting"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id")
        != "futures_v42r2_v41_idle_fund_cost_stress_v1"
        or payload.get("status")
        != "corrected_initial_switch_charge_before_any_v42r2_metric"
        or payload.get("live_trading_allowed") is not False
        or correction["economic_parameters_changed"] is not False
        or correction["parent_inputs_changed"] is not False
        or correction["corrected_behavior"]
        != "apply_initial_purchase_at_first_following_interval"
        or switching["initial_charge_applied_on_first_following_interval"] is not True
        or float(frozen["v39_weight"]) != 0.80
        or float(frozen["cash_carry_weight"]) != 0.20
        or frozen["rebalance_after_initial_allocation"] != "never"
        or tuple(payload["cost_scenarios"]) != engine.COST_SCENARIOS
    ):
        raise ValueError("V42R2 protocol drifted")
    v41 = payload["parents"]["v41"]
    cash = payload["parents"]["idle_cash"]
    v41_root, cash_root = engine._root(v41["root"]), engine._root(cash["root"])
    for section, root in ((v41, v41_root), (cash, cash_root)):
        for key, declaration in section.items():
            if key in {"root", "protocol_sha256"}:
                continue
            path = root / declaration["file"]
            if engine._sha(path) != declaration["sha256"]:
                raise ValueError(f"V42R2 parent drifted: {root.name}.{key}")
            if (
                "rows" in declaration
                and path.suffix == ".parquet"
                and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
            ):
                raise ValueError(f"V42R2 parent rows drifted: {root.name}.{key}")
    v41_manifest = json.loads(
        (v41_root / v41["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    cash_manifest = json.loads(
        (cash_root / cash["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    if (
        v41_manifest["protocol_sha256"] != v41["protocol_sha256"]
        or cash_manifest["protocol_sha256"] != cash["protocol_sha256"]
    ):
        raise ValueError("V42R2 parent protocol identity drifted")
    return engine.Protocol(payload, actual, v41_root, cash_root)


def _switching_costs(eligible: pd.Series, one_way: float) -> pd.Series:
    if eligible.empty or not eligible.between(0.0, 1.0).all() or one_way < 0.0:
        raise ValueError("V42R2 switching inputs invalid")
    costs = eligible.diff().abs().fillna(0.0) * one_way
    initial = float(eligible.iloc[0]) * one_way
    if len(costs) < 2:
        raise ValueError("V42R2 requires a following interval for initial purchase")
    costs.iloc[1] += initial
    costs.iloc[-1] += float(eligible.iloc[-1]) * one_way
    return costs


def build(protocol: engine.Protocol) -> tuple[pd.DataFrame, dict[str, Any]]:
    return engine.build(protocol, switching_cost_function=_switching_costs)


def run(protocol: engine.Protocol) -> Path:
    ledger, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = engine._root(protocol.payload["outputs"]["root"])
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"V42R2 output exists: {output}")
    output.mkdir(parents=True)
    ledger_path = output / "daily_ledger.parquet"
    engine.io_utils._write_parquet(ledger_path, ledger)
    metrics_path = output / "metrics.json"
    write_json(metrics_path, metrics)
    report_path = output / "report.md"
    report = engine._report(metrics).replace("V42R1", "V42R2", 1)
    atomic_write_bytes(report_path, report.encode("utf-8-sig"))
    audit = {
        "checks": {
            "protocol_sha_exact": engine._sha(CONFIG_PATH) == protocol.config_sha256,
            "dates_before_2026": bool(
                pd.to_datetime(ledger["date"]).dt.year.le(2025).all()
            ),
            "nine_fixed_combinations": len(metrics["combinations"]) == 9,
            "weights_exact": metrics["allocation"]
            == {"v39": 0.80, "cash_carry": 0.20, "rebalanced": False},
            "all_nav_positive": bool(
                ledger.filter(regex="__.*nav$").gt(0.0).all(axis=None)
            ),
            "initial_charge_applied_after_start": all(
                float(ledger.loc[1, f"primary__{name}__switching_cost"])
                >= float(ledger.loc[0, "eligible_fraction"])
                * float(values["fund_trade_one_way_fraction"])
                for name, values in protocol.payload["cost_scenarios"].items()
            ),
            "selection_forbidden": metrics["fund_selection_allowed"] is False,
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "invalidated_parent_run": protocol.payload["correction"]["invalidated_run"],
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"V42R2 audit failed: {audit}")
    audit_path = output / "audit.json"
    write_json(audit_path, audit)
    artifacts = {
        "ledger": engine.io_utils._artifact(ledger_path, len(ledger)),
        "metrics": engine.io_utils._artifact(metrics_path),
        "report": engine.io_utils._artifact(report_path),
        "audit": engine.io_utils._artifact(audit_path),
    }
    manifest = {
        "run_id": output.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": protocol.config_sha256,
        "implementation_sha256": engine._sha(Path(__file__)),
        "shared_engine_sha256": engine._sha(Path(engine.__file__)),
        "verdict": metrics["verdict"],
        "same_history_post_result_diagnostic": True,
        "fund_selection_allowed": False,
        "live_trading_allowed": False,
        "artifacts": artifacts,
    }
    manifest_path = output / "manifest.json"
    write_json(manifest_path, manifest)
    atomic_write_bytes(
        output / "manifest.sha256",
        f"{engine._sha(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
    )
    return output


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    output = run(load_protocol())
    print(output)
    print((output / "report.md").read_text(encoding="utf-8-sig"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
