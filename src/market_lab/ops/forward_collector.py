"""Cross-platform dispatcher for immutable forward collectors under systemd."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import requests

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
FORWARD_BOUNDARY: Final[str] = "2026-09-02"
API_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]{32}$")


@dataclass(frozen=True)
class DirectJob:
    module: str
    output_name: str


DIRECT_JOBS: Final[dict[str, DirectJob]] = {
    "cross-market": DirectJob(
        "market_lab.futures.moex_forward_cross_market_bbo_source_v3",
        "moex-cross-market-bbo-v3-cny-perpetual",
    ),
    "broad-carry": DirectJob(
        "market_lab.futures.moex_forward_broad_stock_futures_carry_source_v2",
        "moex-broad-stock-futures-carry-v2-delayed",
    ),
    "option-surface": DirectJob(
        "market_lab.futures.moex_forward_option_surface_source_v2",
        "moex-options-surface-v2-timestamps-margin",
    ),
    "option-surface-eod": DirectJob(
        "market_lab.futures.moex_forward_option_surface_source",
        "moex-options-surface-v1",
    ),
}

STAGED_JOBS: Final[dict[str, tuple[str, str, str]]] = {
    "cash-carry-decision": (
        "market_lab.futures.moex_forward_stock_futures_cash_carry_source",
        "moex-stock-futures-cash-carry-v1",
        "decision",
    ),
    "cash-carry-fill": (
        "market_lab.futures.moex_forward_stock_futures_cash_carry_source",
        "moex-stock-futures-cash-carry-v1",
        "fill",
    ),
    "lqdt-decision": (
        "market_lab.futures.moex_forward_lqdt_idle_cash_source",
        "moex-lqdt-idle-cash-v1",
        "decision",
    ),
    "lqdt-fill": (
        "market_lab.futures.moex_forward_lqdt_idle_cash_source",
        "moex-lqdt-idle-cash-v1",
        "fill",
    ),
    "fund-pool-decision": (
        "market_lab.futures.moex_forward_money_market_fund_pool_source",
        "moex-money-market-fund-pool-v1",
        "decision",
    ),
    "fund-pool-fill": (
        "market_lab.futures.moex_forward_money_market_fund_pool_source",
        "moex-money-market-fund-pool-v1",
        "fill",
    ),
}

PROBED_JOBS: Final[dict[str, dict[str, Any]]] = {
    "cny-relative-value": {
        "module": "market_lab.futures.moex_forward_cny_relative_value_source",
        "output_name": "moex-cny-relative-value-v1",
        "url": (
            "https://iss.moex.com/iss/engines/futures/markets/forts/"
            "securities.json?assets=CNYRUBTOM&iss.meta=off&iss.only=marketdata"
        ),
        "table": "marketdata",
        "date_column": "TRADEDATE",
        "secid_column": "SECID",
        "secid": "CNYRUBF",
        "manifest_path": ("counts", "quote_dates"),
    },
    "moex-rms": {
        "module": "market_lab.futures.moex_forward_rms_source_v2",
        "output_name": "moex-rms-risk-cashflow-v2",
        "url": (
            "https://iss.moex.com/iss/rms/engines/futures/objects/"
            "staticparams.json?iss.meta=off&start=0"
        ),
        "table": "staticparams",
        "date_column": "tradedate",
        "manifest_path": ("risk_source_date",),
    },
}

V27_MODULE: Final[str] = "market_lab.futures.moex_v27_forward_component_source"
V27_FRED_API_MODULE: Final[str] = "market_lab.futures.moex_v27_forward_fred_api_component_source"
V27_FRED_ANONYMOUS_V2_MODULE: Final[str] = (
    "market_lab.futures.moex_v27_forward_fred_anonymous_transport_v2"
)
V27_READINESS_MODULE: Final[str] = "market_lab.futures.v27_forward_component_readiness_v3"
OPTION_QUALITY_MODULE: Final[str] = (
    "market_lab.futures.moex_forward_option_surface_quality_v1"
)
V27_PROBE_URL: Final[str] = (
    "https://iss.moex.com/iss/engines/futures/markets/forts/"
    "securities.json?assets=Si&iss.meta=off&iss.only=marketdata"
)


def _output_root(storage_root: Path, name: str) -> Path:
    return storage_root.resolve() / "data" / "forward" / name


def _run_module(module: str, *arguments: str, required: bool = True) -> str:
    command = [sys.executable, "-m", module, *arguments]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "no diagnostic").splitlines()
        message = detail[-1] if detail else "no diagnostic"
        if required:
            raise RuntimeError(f"{module} failed ({completed.returncode}): {message}")
        print(f"OPTIONAL_FAILURE module={module} detail={message}", file=sys.stderr)
    return completed.stdout


def _audit(module: str, snapshot: Path) -> None:
    output = _run_module(module, "--audit-directory", str(snapshot))
    payload = json.loads(output)
    if payload.get("all_true") is not True:
        raise RuntimeError(f"immutable snapshot failed audit: {snapshot}")


def _manifest_value(manifest: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = manifest
    for part in path:
        value = value[part]
    return value


def _matching_snapshot(
    output_root: Path,
    manifest_path: tuple[str, ...],
    source_date: str,
    module: str,
) -> Path | None:
    for manifest_file in sorted(output_root.glob("snapshot_*/manifest.json")):
        manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
        value = _manifest_value(manifest, manifest_path)
        matches = source_date in value if isinstance(value, list) else str(value) == source_date
        if matches:
            _audit(module, manifest_file.parent)
            return manifest_file.parent
    return None


def _probe_unique_date(spec: dict[str, Any]) -> str:
    response = requests.get(
        str(spec["url"]),
        headers={"User-Agent": "market-lab-linux-forward-collector/1.0"},
        timeout=30,
    )
    response.raise_for_status()
    table = response.json()[str(spec["table"])]
    columns = [str(item) for item in table["columns"]]
    date_index = columns.index(str(spec["date_column"]))
    secid_column = spec.get("secid_column")
    secid_index = columns.index(str(secid_column)) if secid_column else None
    dates = {
        str(row[date_index])
        for row in table["data"]
        if row[date_index] not in (None, "")
        and (secid_index is None or str(row[secid_index]) == str(spec["secid"]))
    }
    if len(dates) != 1:
        raise RuntimeError(f"source probe must expose exactly one date, got {sorted(dates)}")
    source_date = dates.pop()
    if source_date < FORWARD_BOUNDARY:
        raise RuntimeError(f"source date escaped forward boundary: {source_date}")
    return source_date


def _captured_directory(stdout: str, expected_root: Path) -> Path:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("direct collector did not report its snapshot directory")
    snapshot = Path(lines[-1]).resolve()
    root = expected_root.resolve()
    if not snapshot.is_dir() or root not in snapshot.parents:
        raise RuntimeError(f"collector reported an invalid snapshot directory: {snapshot}")
    return snapshot


def _run_direct(job_name: str, job: DirectJob, storage_root: Path) -> None:
    output = _output_root(storage_root, job.output_name)
    stdout = _run_module(job.module, "--output-root", str(output))
    if job_name != "option-surface":
        return
    snapshot = _captured_directory(stdout, output)
    quality_output = _output_root(storage_root, "moex-options-surface-v2-quality-v1")
    _run_module(
        OPTION_QUALITY_MODULE,
        "--snapshot",
        str(snapshot),
        "--output-root",
        str(quality_output),
    )


def _run_staged(spec: tuple[str, str, str], storage_root: Path) -> None:
    module, output_name, stage = spec
    output = _output_root(storage_root, output_name)
    source_date = datetime.now(MOSCOW).strftime("%Y%m%d")
    snapshot = output / f"snapshot_{source_date}_{stage}"
    if snapshot.is_dir():
        _audit(module, snapshot)
        print(f"SKIP source_date={source_date} stage={stage} snapshot={snapshot}")
        return
    _run_module(module, "--stage", stage, "--output-root", str(output))
    if not snapshot.is_dir():
        raise RuntimeError(f"collector created no expected snapshot: {snapshot}")
    _audit(module, snapshot)
    print(f"CAPTURED source_date={source_date} stage={stage} snapshot={snapshot}")


def _run_probed(spec: dict[str, Any], storage_root: Path) -> None:
    module = str(spec["module"])
    output = _output_root(storage_root, str(spec["output_name"]))
    source_date = _probe_unique_date(spec)
    existing = _matching_snapshot(output, tuple(spec["manifest_path"]), source_date, module)
    if existing is not None:
        print(f"SKIP source_date={source_date} snapshot={existing}")
        return
    _run_module(module, "--output-root", str(output))
    created = _matching_snapshot(output, tuple(spec["manifest_path"]), source_date, module)
    if created is None:
        raise RuntimeError(f"collector created no snapshot for source date {source_date}")
    print(f"CAPTURED source_date={source_date} snapshot={created}")


def _v27_existing(
    output_root: Path,
    component: str,
    source_date: str,
    match_source_date: bool,
) -> bool:
    for manifest_file in sorted(output_root.glob("snapshot_*/manifest.json")):
        manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
        if str(manifest.get("component")) != component:
            continue
        if match_source_date:
            matches = source_date in [str(item) for item in manifest["source_dates"]]
        else:
            retrieved = datetime.fromisoformat(
                str(manifest["retrieved_at_utc"]).replace("Z", "+00:00")
            ).astimezone(UTC)
            matches = retrieved.date().isoformat() == source_date
        if not matches:
            continue
        protocol_id = manifest.get("protocol_id")
        if protocol_id == "futures_v27_forward_fred_api_component_v1":
            module = V27_FRED_API_MODULE
        elif protocol_id == "futures_v27_forward_fred_anonymous_transport_v2":
            module = V27_FRED_ANONYMOUS_V2_MODULE
        else:
            module = V27_MODULE
        _audit(module, manifest_file.parent)
        print(
            f"SKIP component={component} source_date={source_date} snapshot={manifest_file.parent}"
        )
        return True
    return False


def _v27_component(
    output: Path,
    component: str,
    source_date: str,
    match_source_date: bool,
    required: bool,
    module: str = V27_MODULE,
) -> None:
    if _v27_existing(output, component, source_date, match_source_date):
        return
    arguments = ["--output-root", str(output)]
    if module == V27_MODULE:
        arguments.extend(["--component", component])
    _run_module(module, *arguments, required=required)


def _run_v27(job_name: str, storage_root: Path) -> None:
    probe_spec = {
        "url": V27_PROBE_URL,
        "table": "marketdata",
        "date_column": "TRADEDATE",
    }
    source_date = _probe_unique_date(probe_spec)
    output = _output_root(storage_root, "v27-validation-v3-components")
    market_component = "market_decision" if job_name == "v27-decision" else "market_execution"
    _v27_component(output, market_component, source_date, True, True)
    _v27_component(output, "macro_cbr", source_date, False, False)
    api_key = os.environ.get("FRED_API_KEY", "")
    if API_KEY_PATTERN.fullmatch(api_key):
        _v27_component(
            output,
            "macro_fred",
            source_date,
            False,
            False,
            V27_FRED_API_MODULE,
        )
    else:
        _v27_component(
            output,
            "macro_fred",
            source_date,
            False,
            False,
            V27_FRED_ANONYMOUS_V2_MODULE,
        )
    _run_module(V27_READINESS_MODULE, "--output-root", str(output))


def run_job(job_name: str, storage_root: Path) -> None:
    if job_name in DIRECT_JOBS:
        _run_direct(job_name, DIRECT_JOBS[job_name], storage_root)
    elif job_name in STAGED_JOBS:
        _run_staged(STAGED_JOBS[job_name], storage_root)
    elif job_name in PROBED_JOBS:
        _run_probed(PROBED_JOBS[job_name], storage_root)
    elif job_name in {"v27-decision", "v27-execution"}:
        _run_v27(job_name, storage_root)
    else:
        raise ValueError(f"unknown forward collector job: {job_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(os.environ.get("MARKET_LAB_STORAGE_ROOT", PROJECT_ROOT)),
    )
    args = parser.parse_args()
    run_job(args.job, args.storage_root)


if __name__ == "__main__":
    main()
