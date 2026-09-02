"""Source-only readiness for the sealed V48 frontier forward program."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import yaml

from market_lab import futures_v48_v47_exact_integer_execution as v48
from market_lab.futures import moex_forward_option_surface_source as option_source
from market_lab.futures import moex_v27_forward_validation_source as v27_source
from market_lab.futures import v27_forward_transport_compatibility as transport
from market_lab.futures import v39_forward_validation_readiness as v39_readiness

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v48_frontier_forward_validation_v1.yaml"
CONFIG_SHA256: Final[str] = (
    "1fbc8c10e3bbe9be2ebc39157b08889ff18aadbe193daa7cecb4f48e6ac54f24"
)


def _sha(path: Path) -> str:
    return transport.sha256_file(path)


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    development = config["development_identity"]
    parents = config["forward_parents"]
    mode = config["fixed_mode"]
    v39_parent = parents["V39"]
    transport_parent = parents["V27_transport"]
    paper_parent = parents["V27_paper"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "v48_frontier_forward_validation_v1"
        or config.get("live_trading_allowed") is not False
        or development["protocol_sha256"] != v48.CONFIG_SHA256
        or development["implementation_sha256"]
        != _sha(PROJECT_ROOT / development["implementation_path"])
        or development["metrics_sha256"]
        != _sha(PROJECT_ROOT / development["canonical_run"] / "metrics.json")
        or development["audit_sha256"]
        != _sha(PROJECT_ROOT / development["canonical_run"] / "audit.json")
        or v39_parent["protocol_sha256"] != v39_readiness.CONFIG_SHA256
        or v39_parent["readiness_sha256"]
        != _sha(PROJECT_ROOT / v39_parent["readiness_path"])
        or transport_parent["compatibility_sha256"] != transport.CONFIG_SHA256
        or transport_parent["source_protocol_sha256"] != v27_source.CONFIG_SHA256
        or paper_parent["protocol_sha256"]
        != _sha(PROJECT_ROOT / paper_parent["protocol_path"])
        or mode["name"] != "frontier"
        or float(mode["V39_mapped_target_multiplier"]) != 1.50
        or float(mode["maximum_gross_notional_multiple"]) != 3.00
        or float(mode["initial_margin_buffer_multiplier"]) != 2.00
        or float(mode["maximum_prior_official_volume_participation"]) != 0.01
        or float(mode["broad_carry_cash_fraction"]) != 0.00
        or mode["selection_after_forward_outcome"] != "forbidden"
    ):
        raise ValueError("V48 frontier forward protocol drifted")
    transport.load_config()
    return config


def assess(
    option_root: Path = option_source.DEFAULT_OUTPUT_ROOT,
    futures_root: Path = v27_source.DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    config = load_config()
    parent = v39_readiness.assess(option_root, futures_root)
    progress = parent["progress"]
    report = {
        "protocol_id": config["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "fixed_mode": {
            "name": config["fixed_mode"]["name"],
            "V39_mapped_target_multiplier": float(
                config["fixed_mode"]["V39_mapped_target_multiplier"]
            ),
            "maximum_gross_notional_multiple": float(
                config["fixed_mode"]["maximum_gross_notional_multiple"]
            ),
            "initial_margin_buffer_multiplier": float(
                config["fixed_mode"]["initial_margin_buffer_multiplier"]
            ),
            "maximum_prior_official_volume_participation": float(
                config["fixed_mode"]["maximum_prior_official_volume_participation"]
            ),
            "broad_carry_cash_fraction": float(
                config["fixed_mode"]["broad_carry_cash_fraction"]
            ),
        },
        "parent_protocol_id": parent["protocol_id"],
        "option_root": parent["option_root"],
        "futures_root": parent["futures_root"],
        "valid_option_weekly_levels": parent["valid_option_weekly_levels"],
        "valid_futures_decision_dates": parent["valid_futures_decision_dates"],
        "valid_futures_execution_dates": parent["valid_futures_execution_dates"],
        "invalid_option_snapshot_count": parent["option_source_invalid_snapshot_count"],
        "invalid_futures_snapshot_count": parent["futures_source_invalid_snapshot_count"],
        "progress": progress,
        "paper_economics_may_start": progress["paper_economics_may_start"],
        "annualization_allowed": progress["cagr_reporting_allowed"],
        "contains_signal_return_or_pnl": False,
        "live_trading_allowed": False,
    }
    if report["paper_economics_may_start"] and not progress["joint_warmup_complete"]:
        raise ValueError("V48 paper admission escaped V39 joint warmup")
    if report["annualization_allowed"] and not progress["evaluation_complete"]:
        raise ValueError("V48 annualization escaped unseen evaluation")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--option-root", type=Path, default=option_source.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--futures-root", type=Path, default=v27_source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.option_root, args.futures_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

