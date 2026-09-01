"""Sealed V1 MOEX CNY/RUB cash-and-carry economic experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import fx_cash_carry_v1 as ledger

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/cny_cash_carry_v1.yaml"
CONFIG_SHA256: Final[str] = "1b9406d92b1cda9f74d8d3cd57b82762256347544a4f1c022287358119a6fae3"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_RUN_ROOT: Final[Path] = PROJECT_ROOT / "runs"


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def load_protocol() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("CNY cash-and-carry config seal mismatch")
    protocol = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        protocol.get("protocol_id") != "cny_cash_carry_v1"
        or protocol.get("live_trading_allowed") is not False
        or protocol["hypothesis"]["reverse_carry_without_proven_cny_borrow"] != "forbidden"
        or protocol["execution"]["cny_interest_percent"] != 0.0
        or protocol["periods"]["protected_ceiling_exclusive"] != "2026-01-01"
        or protocol["scenarios"]["forbidden"]
        != [
            "threshold_search",
            "alternate_entry_days",
            "contract_subset_search",
            "reverse_carry",
        ]
    ):
        raise ValueError("CNY cash-and-carry protocol invariant drift")
    return protocol


def _path(relative: str) -> Path:
    path = (PROJECT_ROOT / relative).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_inputs(
    protocol: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], pd.DataFrame, dict[str, bool], dict[str, str]]:
    protocol = protocol or load_protocol()
    source = protocol["inputs"]["cny_source"]
    ruonia_cfg = protocol["inputs"]["ruonia"]
    paths = {
        "cny_manifest": _path(source["manifest"]),
        "cny_spot": _path(source["spot"]),
        "cny_futures": _path(source["futures"]),
        "ruonia_manifest": _path(ruonia_cfg["manifest"]),
        "ruonia": _path(ruonia_cfg["parquet"]),
    }
    expected = {
        "cny_manifest": source["manifest_sha256"],
        "cny_spot": source["spot_sha256"],
        "cny_futures": source["futures_sha256"],
        "ruonia_manifest": ruonia_cfg["manifest_sha256"],
        "ruonia": ruonia_cfg["parquet_sha256"],
    }
    checks = {
        f"{name}_exact": _sha_file(path) == expected[name] for name, path in paths.items()
    }
    if not all(checks.values()):
        raise ValueError("CNY cash-and-carry source identity mismatch")
    spot = pd.read_parquet(
        paths["cny_spot"],
        columns=[
            "instrument_kind",
            "security_id",
            "trade_date",
            "open",
            "close",
            "number_of_trades",
        ],
    )
    spot["trade_date"] = pd.to_datetime(spot["trade_date"])
    futures = pd.read_parquet(
        paths["cny_futures"],
        columns=[
            "instrument_kind",
            "security_id",
            "asset_code",
            "trade_date",
            "expiration_date",
            "lot_size_cny",
            "open",
            "close",
            "number_of_trades",
            "volume",
        ],
    )
    futures["trade_date"] = pd.to_datetime(futures["trade_date"])
    futures["expiration_date"] = pd.to_datetime(futures["expiration_date"])
    upper = pd.Timestamp(protocol["periods"]["protected_ceiling_exclusive"])
    checks.update(
        {
            "spot_rows_exact": len(spot) == int(source["spot_rows"]),
            "spot_identity_exact": set(spot["security_id"].astype(str))
            == {source["spot_security"]}
            and set(spot["instrument_kind"].astype(str)) == {"spot"},
            "spot_unique": not spot["trade_date"].duplicated().any(),
            "futures_rows_exact": len(futures) == int(source["futures_rows"]),
            "futures_contract_count_exact": futures["security_id"].nunique()
            == int(source["futures_contracts"]),
            "futures_identity_exact": set(futures["asset_code"].astype(str))
            == {source["futures_asset_code"]}
            and set(futures["instrument_kind"].astype(str)) == {"futures"}
            and set(futures["lot_size_cny"].astype(float)) == {float(source["lot_size_cny"])},
            "futures_unique": not futures.duplicated(["security_id", "trade_date"]).any(),
            "protected_rows_absent": spot["trade_date"].max() < upper
            and futures["trade_date"].max() < upper,
        }
    )
    contracts = []
    for secid, frame in futures.groupby("security_id", sort=True):
        expirations = frame["expiration_date"].dropna().unique()
        if len(expirations) != 1:
            raise ValueError(f"CNY futures expiration identity drift: {secid}")
        executable = frame.loc[
            frame["open"].gt(0)
            & frame["close"].gt(0)
            & frame["number_of_trades"].gt(0)
            & frame["volume"].gt(0),
            ["trade_date", "open", "close"],
        ].copy()
        contracts.append(
            {
                "contract_id": f"CNY:{secid}:{pd.Timestamp(expirations[0]).date().isoformat()}",
                "secid": str(secid),
                "expiration_date": pd.Timestamp(expirations[0]),
                "frame": executable.sort_values("trade_date", ignore_index=True),
            }
        )
    checks["all_contracts_have_executable_rows"] = all(
        not item["frame"].empty for item in contracts
    )
    ruonia = pd.read_parquet(
        paths["ruonia"],
        columns=["series_id", "observation_date", "available_at", "value"],
        filters=[("series_id", "==", ruonia_cfg["series_id"])],
    )
    ruonia["available_at"] = pd.to_datetime(ruonia["available_at"], utc=True)
    ruonia["observation_date"] = pd.to_datetime(ruonia["observation_date"])
    ruonia = ruonia.sort_values("available_at", ignore_index=True)
    checks.update(
        {
            "ruonia_identity_exact": set(ruonia["series_id"].astype(str))
            == {ruonia_cfg["series_id"]},
            "ruonia_availability_present": bool(ruonia["available_at"].notna().all()),
            "ruonia_positive": bool((ruonia["value"] > 0).all()),
        }
    )
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(f"CNY cash-and-carry input checks failed: {failed}")
    identities = {name: _sha_file(path) for name, path in paths.items()}
    return spot, contracts, ruonia, checks, identities


def ledger_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    """Adapt the byte-sealed generic two-leg ledger without changing its economics."""
    adapted = json.loads(json.dumps(protocol))
    adapted["inputs"]["si"] = {
        "contract_usd_notional": float(protocol["inputs"]["cny_source"]["lot_size_cny"])
    }
    return adapted


def promotion(
    metrics: dict[str, Any], checks: dict[str, bool], protocol: dict[str, Any]
) -> dict[str, bool]:
    primary = metrics["evaluation"]["primary"]
    stress = metrics["evaluation"]["stress"]
    gates = protocol["promotion_gates"]
    return {
        "evaluation_cagr": primary["cagr"] * 100.0
        >= float(gates["evaluation_cagr_minimum_percent"]),
        "evaluation_sharpe": primary["sharpe"] >= float(gates["evaluation_sharpe_minimum"]),
        "evaluation_max_drawdown": primary["maximum_drawdown"] * 100.0
        <= float(gates["evaluation_max_drawdown_maximum_percent"]),
        "evaluation_positive_years": primary["positive_years"]
        >= int(gates["evaluation_positive_years_minimum"]),
        "evaluation_excess_over_ruonia": primary["excess_over_ruonia_cagr"] * 100.0
        >= float(gates["evaluation_excess_over_ruonia_cagr_minimum_percent"]),
        "stress_evaluation_cagr": stress["cagr"] * 100.0
        >= float(gates["stress_evaluation_cagr_minimum_percent"]),
        "minimum_evaluation_trades": primary["admitted_trade_count"]
        >= int(gates["minimum_evaluation_trades"]),
        "execution_and_identity": all(checks.values()),
    }


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# CNY cash-and-carry V1",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        "| Period | Scenario | CAGR | Sharpe | MDD | Trades | RUONIA CAGR |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for period in ("development", "evaluation"):
        for scenario in ("primary", "stress"):
            item = metrics[period][scenario]
            lines.append(
                f"| {period} | {scenario} | {item['cagr']:.4%} | {item['sharpe']:.3f} | "
                f"{item['maximum_drawdown']:.4%} | {item['admitted_trade_count']} | "
                f"{item['ruonia_benchmark_cagr']:.4%} |"
            )
    lines.extend(["", "## Promotion gates", ""])
    lines.extend(
        f"- {name}: `{passed}`" for name, passed in metrics["promotion_gates"].items()
    )
    lines.extend(
        [
            "",
            "Even a numeric GO remains research-only until future multiyear confirmation.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(run_root: Path = DEFAULT_RUN_ROOT) -> Path:
    protocol = load_protocol()
    spot, contracts, ruonia, source_checks, identities = load_inputs(protocol)
    adapted = ledger_protocol(protocol)
    all_trades, all_daily = [], []
    metrics: dict[str, Any] = {"development": {}, "evaluation": {}}
    execution_checks: dict[str, bool] = {}
    for period in ("development", "evaluation"):
        for scenario in ("primary", "stress"):
            trades, daily, result, checks = ledger.simulate_period(
                spot, contracts, ruonia, adapted, period, scenario
            )
            all_trades.append(trades)
            all_daily.append(daily)
            metrics[period][scenario] = result
            execution_checks.update(
                {f"{period}_{scenario}_{name}": passed for name, passed in checks.items()}
            )
    checks = {**source_checks, **execution_checks}
    gates = promotion(metrics, checks, protocol)
    metrics["promotion_gates"] = gates
    metrics["checks_all_true"] = all(checks.values())
    metrics["numeric_verdict"] = "GO" if all(gates.values()) else "NO_GO"
    metrics["verdict"] = (
        "REQUIRES_FORWARD_CONFIRMATION" if all(gates.values()) else "NO_GO"
    )
    metrics["live_trading_allowed"] = False
    metrics["config_sha256"] = CONFIG_SHA256

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    final = run_root.resolve() / f"cny_cash_carry_v1_{timestamp}_{CONFIG_SHA256[:8]}"
    if final.exists():
        raise FileExistsError(final)
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}-", dir=final.parent))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "config_snapshot.yaml")
        pd.concat(all_trades, ignore_index=True).to_parquet(
            temporary / "trades.parquet", index=False
        )
        pd.concat(all_daily, ignore_index=True).to_parquet(
            temporary / "daily_equity.parquet", index=False
        )
        _write_json(temporary / "metrics.json", metrics)
        (temporary / "report.md").write_text(_report(metrics), encoding="utf-8-sig")
        _write_json(
            temporary / "identity.json",
            {
                "protocol_id": protocol["protocol_id"],
                "config_sha256": CONFIG_SHA256,
                "implementation_sha256": _sha_file(MODULE_PATH),
                "ledger_dependency_sha256": _sha_file(ledger.MODULE_PATH),
                "sources": identities,
            },
        )
        _write_json(temporary / "audit.json", {"checks": checks, "all_true": all(checks.values())})
        names = [
            "config_snapshot.yaml",
            "trades.parquet",
            "daily_equity.parquet",
            "metrics.json",
            "report.md",
            "identity.json",
            "audit.json",
        ]
        _write_json(
            temporary / "artifact_manifest.json",
            {
                name: {
                    "bytes": (temporary / name).stat().st_size,
                    "sha256": _sha_file(temporary / name),
                }
                for name in names
            },
        )
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    if not all(audit(final).values()):
        raise ValueError("CNY cash-and-carry canonical audit failed")
    return final


def audit(run_directory: Path) -> dict[str, bool]:
    identity = json.loads((run_directory / "identity.json").read_text(encoding="utf-8-sig"))
    artifacts = json.loads(
        (run_directory / "artifact_manifest.json").read_text(encoding="utf-8-sig")
    )
    checks = {
        "config_exact": identity["config_sha256"] == CONFIG_SHA256
        and _sha_file(run_directory / "config_snapshot.yaml") == CONFIG_SHA256,
        "implementation_exact": identity["implementation_sha256"] == _sha_file(MODULE_PATH),
        "ledger_dependency_exact": identity["ledger_dependency_sha256"]
        == _sha_file(ledger.MODULE_PATH),
    }
    for name, item in artifacts.items():
        path = run_directory / name
        checks[f"artifact_{name}_exact"] = (
            path.is_file()
            and path.stat().st_size == int(item["bytes"])
            and _sha_file(path) == item["sha256"]
        )
    stored = json.loads((run_directory / "audit.json").read_text(encoding="utf-8-sig"))
    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8-sig"))
    checks["stored_execution_audit_all_true"] = stored["all_true"] is True
    checks["live_trading_stays_false"] = metrics["live_trading_allowed"] is False
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(run(args.run_root))


if __name__ == "__main__":
    main()
