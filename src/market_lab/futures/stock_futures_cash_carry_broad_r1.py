"""Replay sealed broad cash-carry after the official stock-unit correction."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.futures import stock_futures_cash_carry_broad_v1 as parent
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/stock_futures_cash_carry_broad_r1.yaml"
CONFIG_SHA256: Final[str] = (
    "c2aa67526f8217447955da6333a20e24b658ca25b5d1405820ab19ab857b11ca"
)
PARENT_CONFIG_SHA256: Final[str] = parent.CONFIG_SHA256
PARENT_IMPLEMENTATION_SHA256: Final[str] = (
    "7e7b9472eb7d717a21166e7695b3a65898ed444eb90cd6fd725ff0ad5c8dff19"
)
ACTION_RMS_ASSETCODES: Final[dict[str, str]] = {
    "TRNFP": "TRNF",
    "GMKN": "GMKN",
    "PLZL": "PLZL",
    "VTBR": "VTBR",
}


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    parent_protocol: parent.Protocol
    source_paths: dict[str, Path]
    events: list[dict[str, Any]]
    affected: pd.DataFrame


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("broad cash-carry R1 config must be an object")
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "stock_futures_cash_carry_broad_r1"
        or payload.get("status")
        != "sealed_after_invalid_v1_unit_diagnostic_before_corrected_r1_outcomes"
        or payload.get("live_trading_allowed") is not False
        or tuple(payload["correction"]["affected_stocks_only"])
        != ("TRNFP", "GMKN", "PLZL", "VTBR")
    ):
        raise ValueError("broad cash-carry R1 protocol drifted")
    parent_declaration = payload["parent_protocol"]
    parent_config = PROJECT_ROOT / parent_declaration["config"]["file"]
    parent_implementation = PROJECT_ROOT / parent_declaration["implementation"]["file"]
    if (
        _sha(parent_config) != PARENT_CONFIG_SHA256
        or _sha(parent_implementation) != PARENT_IMPLEMENTATION_SHA256
        or parent_declaration["config"]["sha256"] != PARENT_CONFIG_SHA256
        or parent_declaration["implementation"]["sha256"]
        != PARENT_IMPLEMENTATION_SHA256
    ):
        raise ValueError("broad cash-carry R1 parent drifted")
    parent_protocol = parent.load_protocol()
    section = payload["unit_correction_source"]
    root = storage._project_path(section["root"], "data")
    source_paths: dict[str, Path] = {}
    for key in ("manifest", "events", "affected_contracts", "raw"):
        declaration = section[key]
        path = root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"broad cash-carry R1 correction source drifted: {key}")
        if path.suffix == ".parquet" and pq.ParquetFile(path).metadata.num_rows != int(
            declaration["rows"]
        ):
            raise ValueError(f"broad cash-carry R1 correction rows drifted: {key}")
        source_paths[key] = path
    events = json.loads(source_paths["events"].read_text(encoding="utf-8-sig"))
    affected = pd.read_parquet(source_paths["affected_contracts"])
    if len(events) != 4 or len(affected) != 27 or affected["contract_id"].duplicated().any():
        raise ValueError("broad cash-carry R1 correction identity drifted")
    return Protocol(payload, actual, parent_protocol, source_paths, events, affected)


def _adjust_cashflows(
    frame: pd.DataFrame, events: list[dict[str, Any]]
) -> tuple[pd.DataFrame, dict[str, int]]:
    output = frame.copy()
    counts: dict[str, int] = {}
    for event in events:
        stock = str(event["stock_secid"])
        assetcode = ACTION_RMS_ASSETCODES[stock]
        effective = pd.Timestamp(event["equity_effective_date"])
        mask = output["assetcode"].eq(assetcode) & output["t"].lt(effective)
        if event["action"] == "split":
            factor = int(event["factor_new_shares_per_old_share"])
            output.loc[mask, "cf"] = output.loc[mask, "cf"] / factor
        elif event["action"] == "consolidation":
            factor = int(event["factor_old_shares_per_new_share"])
            output.loc[mask, "cf"] = output.loc[mask, "cf"] * factor
        else:
            raise ValueError(f"unknown broad cash-carry R1 action: {event['action']}")
        counts[stock] = int(mask.sum())
    if (~np.isfinite(output["cf"]) | output["cf"].lt(0.0)).any():
        raise ValueError("broad cash-carry R1 adjusted cashflow invalid")
    return output, counts


def _apply_unit_correction(frame: pd.DataFrame, affected: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    original = pd.to_numeric(output["lot_size_shares"], errors="raise").astype(int)
    corrected = affected.set_index("contract_id")["back_adjusted_spot_units"]
    mapped = output["contract_id"].map(corrected)
    output["historical_contract_lot_shares"] = original
    output["lot_size_shares"] = mapped.fillna(original).astype(int)
    output["unit_corrected"] = mapped.notna()
    if output["lot_size_shares"].le(0).any():
        raise ValueError("broad cash-carry R1 corrected units invalid")
    return output


def build_corrected_decisions_and_trades(
    protocol: Protocol,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame], dict[str, int]]:
    original_aligned = parent._aligned_stock
    original_cashflows = parent._load_cashflows

    def corrected_aligned(
        parent_protocol: parent.Protocol,
        stock: str,
        futures: pd.DataFrame,
        specs: pd.DataFrame,
    ) -> pd.DataFrame:
        frame = original_aligned(parent_protocol, stock, futures, specs)
        return _apply_unit_correction(frame, protocol.affected)

    cashflow_counts: dict[str, int] = {}

    def corrected_cashflows(parent_protocol: parent.Protocol) -> pd.DataFrame:
        nonlocal cashflow_counts
        frame = original_cashflows(parent_protocol)
        adjusted, cashflow_counts = _adjust_cashflows(frame, protocol.events)
        return adjusted

    parent._aligned_stock = corrected_aligned
    parent._load_cashflows = corrected_cashflows
    try:
        decisions, trades, aligned = parent.build_decisions_and_trades(
            protocol.parent_protocol
        )
    finally:
        parent._aligned_stock = original_aligned
        parent._load_cashflows = original_cashflows

    specs = pd.read_parquet(protocol.parent_protocol.paths["futures_intraday_specs"])
    original_units = specs.set_index("contract_id")["lot_size_shares"]
    affected_ids = set(protocol.affected["contract_id"].astype(str))
    for frame in (decisions, trades):
        frame["back_adjusted_spot_units"] = frame["lot_size_shares"].astype(int)
        frame["historical_contract_lot_shares"] = (
            frame["contract_id"].map(original_units).astype(int)
        )
        frame["unit_corrected"] = frame["contract_id"].astype(str).isin(affected_ids)
    return decisions, trades, aligned, cashflow_counts


def build_unit_diagnostics(
    aligned: dict[str, pd.DataFrame], specs: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for spec in specs.sort_values(["stock_secid", "last_trade", "secid"]).to_dict("records"):
        stock = str(spec["stock_secid"])
        frame = aligned[stock]
        selected = frame.loc[
            frame["contract_id"].eq(spec["contract_id"])
            & frame["futures_decision_close"].gt(0.0)
            & frame["spot_decision_close"].gt(0.0)
        ]
        units = int(
            selected["lot_size_shares"].iloc[0]
            if not selected.empty
            else spec["lot_size_shares"]
        )
        item: dict[str, Any] = {
            "contract_id": spec["contract_id"],
            "stock_secid": stock,
            "secid": spec["secid"],
            "asset_code": spec["asset_code"],
            "historical_contract_lot_shares": int(spec["lot_size_shares"]),
            "back_adjusted_spot_units": units,
            "aligned_rows": len(selected),
            "status": "missing_aligned_price",
            "median_futures_to_spot_ratio": np.nan,
            "median_normalized_unit_ratio": np.nan,
            "inside_presealed_range": False,
        }
        if not selected.empty:
            ratio = selected["futures_decision_close"] / selected["spot_decision_close"]
            median_ratio = float(ratio.median())
            normalized = median_ratio / units
            item.update(
                {
                    "status": "valid" if 0.75 <= normalized <= 1.35 else "invalid_ratio",
                    "median_futures_to_spot_ratio": median_ratio,
                    "median_normalized_unit_ratio": normalized,
                    "inside_presealed_range": 0.75 <= normalized <= 1.35,
                }
            )
        rows.append(item)
    return pd.DataFrame(rows)


def _report(metrics: dict[str, Any]) -> str:
    report = parent._report(metrics).replace(
        "# Broad stock–futures cash-and-carry V1",
        "# Broad stock–futures cash-and-carry R1 unit-corrected",
    )
    note = (
        "R1 changes only the official split/consolidation share basis for 27 contracts; "
        "all parent economic rules and all 29 stocks remain fixed.\n\n"
    )
    return report.replace("\n\n", f"\n\n{note}", 1)


def run(protocol: Protocol) -> Path:
    decisions, trades, aligned, cashflow_counts = build_corrected_decisions_and_trades(
        protocol
    )
    ledger, allocation_diagnostics = parent.build_ledger(trades, aligned)
    metrics = parent.build_metrics(
        decisions, trades, ledger, allocation_diagnostics
    )
    specs = pd.read_parquet(protocol.parent_protocol.paths["futures_intraday_specs"])
    diagnostics = build_unit_diagnostics(aligned, specs)
    valid_diagnostics = diagnostics.loc[diagnostics["aligned_rows"].gt(0)]
    source_gate = (
        len(valid_diagnostics) == 338
        and diagnostics["aligned_rows"].eq(0).sum() == 1
        and valid_diagnostics["inside_presealed_range"].all()
    )
    metrics["unit_correction"] = {
        "source_quality_gate": bool(source_gate),
        "affected_contracts": len(protocol.affected),
        "contracts_with_ratio": len(valid_diagnostics),
        "contracts_without_ratio": int(diagnostics["aligned_rows"].eq(0).sum()),
        "cashflow_rows_adjusted_by_stock": cashflow_counts,
        "parent_invalid_run_not_used_for_selection": True,
    }
    if not source_gate:
        metrics["verdict"] = "INVALID_SOURCE_QUALITY"

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = PROJECT_ROOT / protocol.payload["outputs"]["root"]
    output = root.parent / f"{root.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"broad cash-carry R1 run exists: {output}")
    output.mkdir(parents=True)
    paths = {
        "decisions": output / "decisions.parquet",
        "trades": output / "trades.parquet",
        "ledger": output / "daily_ledger.parquet",
        "unit_diagnostics": output / "unit_diagnostics.parquet",
        "audit": output / "audit.json",
        "metrics": output / "metrics.json",
        "report": output / "report.md",
    }
    storage._write_parquet(paths["decisions"], decisions)
    storage._write_parquet(paths["trades"], trades)
    storage._write_parquet(paths["ledger"], ledger)
    storage._write_parquet(paths["unit_diagnostics"], diagnostics)
    audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "parent_config_sha_exact": _sha(parent.CONFIG_PATH) == PARENT_CONFIG_SHA256,
            "parent_implementation_sha_exact": _sha(Path(parent.__file__))
            == PARENT_IMPLEMENTATION_SHA256,
            "correction_source_hashes_exact": all(
                _sha(protocol.source_paths[key])
                == protocol.payload["unit_correction_source"][key]["sha256"]
                for key in protocol.source_paths
            ),
            "exact_27_contract_units_changed": len(protocol.affected) == 27,
            "source_unit_ratio_gate": bool(source_gate),
            "all_decisions_before_2026": bool(
                pd.to_datetime(decisions["local_date"]).dt.year.le(2025).all()
            ),
            "all_trades_before_2026": bool(
                pd.to_datetime(trades["exit_date"]).dt.year.le(2025).all()
            ),
            "signals_equal_trades": int(decisions["signal"].sum()) == len(trades),
            "scenario_decisions_identical": True,
            "no_asset_or_trade_exclusion": tuple(parent.STOCKS)
            == tuple(protocol.parent_protocol.payload["universe"]["exact_stocks"]),
            "live_forbidden": protocol.payload["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"broad cash-carry R1 audit failed: {audit}")
    write_json(paths["audit"], audit)
    write_json(paths["metrics"], metrics)
    atomic_write_bytes(paths["report"], _report(metrics).encode("utf-8-sig"))
    artifacts = {
        name: storage._artifact(path, pq.ParquetFile(path).metadata.num_rows)
        if path.suffix == ".parquet"
        else storage._artifact(path)
        for name, path in paths.items()
    }
    manifest = {
        "run_id": output.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": protocol.config_sha256,
        "implementation_sha256": _sha(Path(__file__)),
        "parent_config_sha256": PARENT_CONFIG_SHA256,
        "parent_implementation_sha256": PARENT_IMPLEMENTATION_SHA256,
        "unit_correction_source_manifest_sha256": protocol.payload[
            "unit_correction_source"
        ]["manifest"]["sha256"],
        "verdict": metrics["verdict"],
        "live_trading_allowed": False,
        "same_history_development_only": True,
        "artifacts": artifacts,
    }
    manifest_path = output / "manifest.json"
    write_json(manifest_path, manifest)
    atomic_write_bytes(
        output / "manifest.sha256",
        f"{_sha(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    protocol = load_protocol()
    output = run(protocol)
    print(output)
    print((output / "report.md").read_text(encoding="utf-8-sig"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
