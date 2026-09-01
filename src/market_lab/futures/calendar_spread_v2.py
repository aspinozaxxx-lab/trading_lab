"""Empty-trade metric-schema correction for sealed calendar-spread V1."""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab.futures import calendar_spread_v1 as v1
from market_lab.futures import moex_calendar_spread_source as source

PROJECT_ROOT: Final[Path] = v1.PROJECT_ROOT
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/calendar_spread_v2.yaml"
EXPECTED_PARENT_CONFIG_SHA: Final[str] = (
    "e74dab97ab65a28d4fc16f0061952545606ccccd1df7a8c677a8c8bc2af2b3bc"
)
EXPECTED_PARENT_MODULE_SHA: Final[str] = (
    "f8d0108e87c0c1eed5e841aab35e1bc2f59485e67ce3bd18aed9920c16213282"
)


@dataclass(frozen=True, slots=True)
class CorrectionProtocol:
    """V2 overlay and an exact inherited V1 economic protocol."""

    payload: dict[str, Any]
    config_sha256: str
    economic: v1.EconomicProtocol


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"calendar spread V2 {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"calendar spread V2 sidecar missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def load_protocol(config_path: Path = CONFIG_PATH) -> CorrectionProtocol:
    """Verify the correction overlay and all byte-identical parent identities."""
    path = config_path.resolve()
    config_sha = source.sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("calendar spread V2 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("calendar spread V2 protocol must be a YAML object")
    parent = _mapping(payload.get("parent_V1"), "parent")
    failure = _mapping(payload.get("V1_failure"), "failure")
    delta = _mapping(payload.get("only_delta"), "delta")
    output = _mapping(payload.get("output"), "output")
    if (
        payload.get("protocol_id") != "calendar_spread_economic_v2"
        or payload.get("status")
        != "predeclared_after_V1_empty_trade_metric_failure_before_any_reported_outcome"
        or payload.get("sealed_before_any_reported_outcome") is not True
        or payload.get("live_trading_allowed") is not False
        or parent.get("config_sha256") != EXPECTED_PARENT_CONFIG_SHA
        or parent.get("implementation_sha256") != EXPECTED_PARENT_MODULE_SHA
        or parent.get(
            "inherited_hypotheses_features_models_splits_portfolio_execution_costs_and_gates"
        )
        != "byte_identical"
        or failure.get("canonical_output_created") is not False
        or failure.get("metric_or_return_value_printed") is not False
        or delta.get("scope") != "empty_trade_metric_schema_adapter"
        or delta.get("signals_changed") is not False
        or delta.get("execution_or_accounting_changed") is not False
        or delta.get("validation_gates_changed") is not False
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("calendar spread V2 invariants drifted")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, expected in dependencies.items():
        if source.sha256_file(PROJECT_ROOT / str(relative)) != str(expected).lower():
            raise ValueError(f"calendar spread V2 dependency drift: {relative}")
    parent_protocol = v1.load_protocol()
    if parent_protocol.config_sha256 != EXPECTED_PARENT_CONFIG_SHA:
        raise ValueError("calendar spread V2 parent config drifted")
    economic_payload = copy.deepcopy(parent_protocol.payload)
    economic_payload["protocol_id"] = "calendar_spread_economic_v2"
    economic_payload["status"] = str(payload["status"])
    economic_payload["output"] = {
        **economic_payload["output"],
        "directory": str(output["directory"]),
    }
    economic = v1.EconomicProtocol(
        payload=economic_payload,
        config_sha256=config_sha,
        output_directory=source._project_path(str(output["directory"]), "runs"),
        input_paths=parent_protocol.input_paths,
    )
    return CorrectionProtocol(
        payload=payload,
        config_sha256=config_sha,
        economic=economic,
    )


def corrected_period_metrics(
    daily: pd.DataFrame,
    trades: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    """Supply stable empty Series while preserving parent behavior otherwise."""
    normalized = trades.copy()
    if "status" not in normalized:
        normalized["status"] = pd.Series(
            pd.NA, index=normalized.index, dtype="string"
        )
    if "net_pnl" not in normalized:
        normalized["net_pnl"] = pd.Series(
            np.nan, index=normalized.index, dtype="float64"
        )
    return _PARENT_PERIOD_METRICS(daily, normalized, start, end)


_PARENT_PERIOD_METRICS: Final = v1._period_metrics


@contextlib.contextmanager
def _correction_context() -> Iterator[None]:
    original_metrics = v1._period_metrics
    original_config = v1.CONFIG_PATH
    v1._period_metrics = corrected_period_metrics
    v1.CONFIG_PATH = CONFIG_PATH
    try:
        yield
    finally:
        v1._period_metrics = original_metrics
        v1.CONFIG_PATH = original_config


def run_experiment(protocol: CorrectionProtocol | None = None) -> Path:
    """Run V1 byte-identically except for the empty metric schema adapter."""
    protocol = protocol or load_protocol()
    with _correction_context():
        return v1.run_experiment(protocol.economic)


def audit_bundle(protocol: CorrectionProtocol | None = None) -> dict[str, bool]:
    """Delegate immutable artifact audit with the V2 protocol identity."""
    protocol = protocol or load_protocol()
    return v1.audit_bundle(protocol.economic)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.audit_only:
        print(json.dumps(audit_bundle(), ensure_ascii=False, indent=2))
    else:
        print(run_experiment())


if __name__ == "__main__":
    main()
