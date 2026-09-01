"""Adaptive Last-price/source-width correction for calendar-spread V2."""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import calendar_spread_v1 as v1
from market_lab.futures import calendar_spread_v2 as v2
from market_lab.futures import moex_calendar_spread_source as source

PROJECT_ROOT: Final[Path] = v1.PROJECT_ROOT
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/calendar_spread_v3.yaml"
EXPECTED_V2_CONFIG_SHA: Final[str] = (
    "e986530265ab6c87c39fbb6315dcb39d1eb80b971ff58d8614bff5966bb4a1eb"
)
EXPECTED_V2_MODULE_SHA: Final[str] = (
    "9d96dfe361f519fe5311751c7b0c3237db802e54a18e9bc6097e8bb61e29468e"
)
EXPECTED_V2_MANIFEST_SHA: Final[str] = (
    "facc159f6c8aa063d2cdd584de414f3cf28970c7c6fc8e63b231ded39cb9ed88"
)
EXPECTED_V2_METRICS_SHA: Final[str] = (
    "c43a3f0b42e4816eb741ef325e4cc5fec3ac3ba05619a76fd4ee465e4222cfff"
)


@dataclass(frozen=True, slots=True)
class SourceCorrectionProtocol:
    """V3 overlay plus the inherited V1-compatible economic payload."""

    payload: dict[str, Any]
    config_sha256: str
    economic: v1.EconomicProtocol


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"calendar spread V3 {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"calendar spread V3 sidecar missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def load_protocol(config_path: Path = CONFIG_PATH) -> SourceCorrectionProtocol:
    """Verify V3 and the immutable V2 code/result identities without market reads."""
    path = config_path.resolve()
    config_sha = source.sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("calendar spread V3 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("calendar spread V3 protocol must be a YAML object")
    parent = _mapping(payload.get("parent_V2"), "parent")
    diagnosis = _mapping(payload.get("sealed_V2_diagnosis"), "diagnosis")
    correction = _mapping(
        payload.get("source_semantics_correction"), "source correction"
    )
    inheritance = _mapping(payload.get("inheritance_from_V2_and_V1"), "inheritance")
    output = _mapping(payload.get("output"), "output")
    if (
        payload.get("protocol_id") != "calendar_spread_economic_v3"
        or payload.get("status")
        != "post_V2_adaptive_source_semantics_correction_predeclared_before_V3_outcomes"
        or payload.get("sealed_before_V3_outcomes") is not True
        or payload.get("independent_confirmation") is not False
        or payload.get("live_trading_allowed") is not False
        or parent.get("config_sha256") != EXPECTED_V2_CONFIG_SHA
        or parent.get("implementation_sha256") != EXPECTED_V2_MODULE_SHA
        or parent.get("canonical_manifest_sha256") != EXPECTED_V2_MANIFEST_SHA
        or parent.get("canonical_metrics_sha256") != EXPECTED_V2_METRICS_SHA
        or int(diagnosis.get("total_plans", -1)) != 13
        or int(diagnosis.get("evaluation_2024_2025_plans", -1)) != 0
        or correction.get("signal_price_after")
        != "factual_reported_last_trade_price"
        or correction.get("EOD_quote_width_used_as_entry_admission") is not False
        or correction.get("strict_positive_closing_quote_width_still_required")
        is not True
        or inheritance.get("no_other_change") is not True
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("calendar spread V3 invariants drifted")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, expected in dependencies.items():
        if source.sha256_file(PROJECT_ROOT / str(relative)) != str(expected).lower():
            raise ValueError(f"calendar spread V3 dependency drift: {relative}")
    v2_protocol = v2.load_protocol()
    if v2_protocol.config_sha256 != EXPECTED_V2_CONFIG_SHA:
        raise ValueError("calendar spread V3 parent V2 drifted")
    v2_output = v2_protocol.economic.output_directory
    if (
        source.sha256_file(v2_output / "manifest.json") != EXPECTED_V2_MANIFEST_SHA
        or source.sha256_file(v2_output / "metrics.json") != EXPECTED_V2_METRICS_SHA
    ):
        raise ValueError("calendar spread V3 canonical V2 result drifted")
    economic_payload = copy.deepcopy(v2_protocol.economic.payload)
    economic_payload["protocol_id"] = "calendar_spread_economic_v3"
    economic_payload["status"] = str(payload["status"])
    economic_payload["information_set"]["signal_price"] = (
        "factual_reported_last_trade_price"
    )
    economic_payload["features"]["EOD_quote_width_used_as_entry_admission"] = False
    economic_payload["output"] = {
        **economic_payload["output"],
        "directory": str(output["directory"]),
    }
    economic = v1.EconomicProtocol(
        payload=economic_payload,
        config_sha256=config_sha,
        output_directory=source._project_path(str(output["directory"]), "runs"),
        input_paths=v2_protocol.economic.input_paths,
    )
    return SourceCorrectionProtocol(
        payload=payload,
        config_sha256=config_sha,
        economic=economic,
    )


_PARENT_BUILD_FEATURE_FRAME: Final = v1.build_feature_frame
_PARENT_BUILD_TRADE_PLANS: Final = v1.build_trade_plans


def build_last_trade_feature_frame(active: pd.DataFrame) -> pd.DataFrame:
    """Use factual reported Last as the sole signal-price series."""
    if "last" not in active or "quote_midpoint" not in active:
        raise ValueError("calendar spread V3 active frame lacks Last or midpoint")
    corrected = active.copy()
    corrected["quote_midpoint"] = corrected["last"]
    return _PARENT_BUILD_FEATURE_FRAME(corrected)


def build_width_independent_trade_plans(
    features: pd.DataFrame, protocol_payload: Mapping[str, Any]
) -> pd.DataFrame:
    """Retain width as a feature but remove it from next-open admission."""
    planning = features.copy()
    planning["quote_width"] = 0.0
    return _PARENT_BUILD_TRADE_PLANS(planning, protocol_payload)


@contextlib.contextmanager
def _correction_context() -> Iterator[None]:
    original_metrics = v1._period_metrics
    original_feature_builder = v1.build_feature_frame
    original_plan_builder = v1.build_trade_plans
    original_config = v1.CONFIG_PATH
    v1._period_metrics = v2.corrected_period_metrics
    v1.build_feature_frame = build_last_trade_feature_frame
    v1.build_trade_plans = build_width_independent_trade_plans
    v1.CONFIG_PATH = CONFIG_PATH
    try:
        yield
    finally:
        v1._period_metrics = original_metrics
        v1.build_feature_frame = original_feature_builder
        v1.build_trade_plans = original_plan_builder
        v1.CONFIG_PATH = original_config


def run_experiment(protocol: SourceCorrectionProtocol | None = None) -> Path:
    """Run inherited economics under only the sealed V3 source semantics."""
    protocol = protocol or load_protocol()
    with _correction_context():
        return v1.run_experiment(protocol.economic)


def audit_bundle(protocol: SourceCorrectionProtocol | None = None) -> dict[str, bool]:
    """Delegate immutable bundle audit with the V3 identity."""
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
