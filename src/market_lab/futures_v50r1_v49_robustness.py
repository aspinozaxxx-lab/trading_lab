"""Calendar-basis correction for the sealed V50 V49 robustness audit."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab import futures_v50_v49_robustness as base

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v50r1_v49_robustness_audit_v1.yaml"
_BASE_VERIFY = base.verify_curves
_ROBUST_PERFORMANCE = base.robust.performance_metrics


def _sha(path: Path) -> str:
    return base._sha(path)


def _v49_performance_metrics(
    levels: pd.Series,
    dates: pd.Series,
    *,
    initial_cash: float,
) -> dict[str, float]:
    """Replay V49 metrics with its exact 365.25-day calendar convention."""

    values = np.r_[float(initial_cash), levels.to_numpy(dtype=float)]
    returns = pd.Series(values).pct_change().dropna()
    total_return = float(values[-1] / initial_cash - 1.0)
    elapsed_days = max(
        (pd.Timestamp(dates.iloc[-1]) - pd.Timestamp(dates.iloc[0])).days,
        1,
    )
    years = elapsed_days / 365.25
    cagr = float((values[-1] / initial_cash) ** (1.0 / years) - 1.0)
    deviation = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    sharpe = float(np.sqrt(252.0) * returns.mean() / deviation) if deviation > 0.0 else 0.0
    peaks = np.maximum.accumulate(values)
    maximum_drawdown = float(np.max(1.0 - values / peaks))
    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": maximum_drawdown,
    }


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load R1 and return the unchanged V50 protocol plus one metric correction."""

    config_path = config_path.resolve()
    declared = config_path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    correction = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(correction, dict):
        raise ValueError("V50R1 correction must be an object")
    parent = correction["parent_v50"]
    implementation = correction["implementation"]
    exact = correction["metric_correction"]
    if (
        _sha(config_path) != declared
        or correction.get("protocol_id") != "v50r1_v49_robustness_audit_v1"
        or correction.get("status")
        != "sealed_after_v50_preflight_metric_mismatch_before_any_resampling"
        or correction.get("live_trading_allowed") is not False
        or _sha(PROJECT_ROOT / parent["config_path"]) != parent["protocol_sha256"]
        or _sha(PROJECT_ROOT / implementation["wrapper_path"]) != implementation["wrapper_sha256"]
        or _sha(PROJECT_ROOT / implementation["engine_path"]) != implementation["engine_sha256"]
        or float(exact["incorrect_V27_calendar_year_days"]) != 365.2425
        or float(exact["correct_V49_calendar_year_days"]) != 365.25
        or exact["correction_scope"] != "canonical_V49_metric_replay_only"
        or float(exact["bootstrap_calendar_year_days_unchanged"]) != 365.2425
        or exact["bootstrap_seeds_blocks_replications_windows_gates_changed"] is not False
        or exact["strategy_or_execution_changed"] is not False
        or exact["V50_output_created_before_correction"] is not False
    ):
        raise ValueError("V50R1 correction drifted")
    parent_protocol = yaml.safe_load(
        (PROJECT_ROOT / parent["config_path"]).read_text(encoding="utf-8-sig")
    )
    protocol = copy.deepcopy(parent_protocol)
    protocol["protocol_id"] = correction["protocol_id"]
    protocol["status"] = correction["status"]
    protocol["declared_at_utc"] = correction["declared_at_utc"]
    protocol["metric_correction"] = exact
    protocol["correction_identity"] = {
        "protocol_sha256": _sha(config_path),
        "parent_protocol_sha256": parent["protocol_sha256"],
        "wrapper_sha256": implementation["wrapper_sha256"],
        "engine_sha256": implementation["engine_sha256"],
    }
    return protocol


def verify_curves(protocol: dict[str, Any], runs_root: Path) -> base.VerifiedCurves:
    """Use the unchanged verifier with only the exact V49 CAGR clock substituted."""

    base.robust.performance_metrics = _v49_performance_metrics
    try:
        return _BASE_VERIFY(protocol, runs_root)
    finally:
        base.robust.performance_metrics = _ROBUST_PERFORMANCE


def _activate() -> None:
    base.CONFIG_PATH = CONFIG_PATH
    base.load_protocol = load_protocol
    base.verify_curves = verify_curves


def main() -> int:
    _activate()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CONFIG_PATH", "load_protocol", "main", "verify_curves"]
