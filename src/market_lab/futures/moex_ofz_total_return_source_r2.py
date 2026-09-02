"""Correct OFZ bondization pagination to the global MOEX start parameter."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlencode

import yaml

from market_lab.futures import moex_ofz_total_return_source as base
from market_lab.futures import moex_ofz_total_return_source_r1 as r1

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_ofz_total_return_source_r2.yaml"
MODULE_PATH: Final[Path] = Path(__file__).resolve()


def _sha(path: Path) -> str:
    return base._sha_file(path)


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    correction = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(correction, dict):
        raise ValueError("OFZ R2 correction must be an object")
    parent = correction["parent_r1"]
    implementation = correction["implementation"]
    transport = correction["transport_correction"]
    if (
        actual != declared
        or correction.get("protocol_id") != "moex_ofz_total_return_source_r2"
        or correction.get("status") != "sealed_after_r1_schedule_cursor_failure_before_any_output"
        or correction.get("live_trading_allowed") is not False
        or _sha(PROJECT_ROOT / parent["config_path"]) != parent["protocol_sha256"]
        or _sha(PROJECT_ROOT / parent["implementation_path"]) != parent["implementation_sha256"]
        or _sha(PROJECT_ROOT / implementation["path"]) != implementation["sha256"]
        or transport["R1_output_created"] is not False
        or transport["market_fields_or_economics_changed"] is not False
        or transport["incorrect_parameter"] != "per_block_namespaced_start"
        or transport["correct_parameter"] != "global_start"
    ):
        raise ValueError("OFZ R2 correction drifted")
    config = copy.deepcopy(r1.load_config())
    config["protocol_id"] = correction["protocol_id"]
    config["status"] = correction["status"]
    config["declared_at_utc"] = correction["declared_at_utc"]
    config["implementation"] = implementation
    config["schedule_transport_correction"] = transport
    config["source"]["bondization"]["pagination_parameter"] = "global_start"
    return config


def schedule_url(config: dict[str, Any], secid: str, kind: str, start: int) -> str:
    if kind not in base.SCHEDULE_KINDS or not secid.startswith("SU"):
        raise ValueError("undeclared OFZ schedule request")
    source = config["source"]["bondization"]
    endpoint = source["endpoint_template"].format(secid=secid)
    query = {
        "iss.meta": "off",
        "iss.only": f"{kind},{kind}.cursor",
        "start": start,
    }
    return f"{endpoint}?{urlencode(query)}"


def _activate() -> None:
    r1._activate()
    base.CONFIG_PATH = CONFIG_PATH
    base.MODULE_PATH = MODULE_PATH
    base.load_config = load_config
    base.schedule_url = schedule_url


def main() -> None:
    _activate()
    base.main()


if __name__ == "__main__":
    main()


__all__ = ["CONFIG_PATH", "load_config", "main", "schedule_url"]
