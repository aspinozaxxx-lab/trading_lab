"""V49 paper-arm readiness admitting the anonymous FRED transport V2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from market_lab.futures import moex_forward_option_surface_source as option_source
from market_lab.futures import moex_v27_forward_component_source as component_source
from market_lab.futures import v49_double_risk_forward_readiness_v2 as forward_readiness
from market_lab.futures import v49_double_risk_paper_readiness as parent


def load_config() -> dict[str, Any]:
    config = parent.load_config()
    forward_readiness.load_config()
    return config


def assess(
    option_root: Path = option_source.DEFAULT_OUTPUT_ROOT,
    component_root: Path = component_source.DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    config = load_config()
    boundary = parent._timestamp(
        config["paper_boundary"]["earliest_eligible_retrieved_at_utc"]
    )
    return forward_readiness._assess_sources(
        config,
        boundary,
        option_root,
        component_root,
        protocol_id=config["protocol_id"],
        protocol_sha256=parent.CONFIG_SHA256,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--option-root", type=Path, default=option_source.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--component-root", type=Path, default=component_source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.option_root, args.component_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
