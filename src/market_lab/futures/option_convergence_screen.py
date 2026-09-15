"""V92: one closed metadata map, then an independently admitted V90 economic screen."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from market_lab.futures import option_convergence_inputs as inputs
from market_lab.futures import option_strike_convergence as rule

base, reporting, mapper = inputs.base, inputs.reporting, inputs.mapper
CONFIG = base.PROJECT / "configs/v92_option_convergence_screen_v1.json"
SEAL = base.PROJECT / "configs/v92_option_convergence_screen_v1.seal.json"


def load_protocol(expected):
    seal = inputs.checked_json(SEAL, expected)
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V92 code closure drift")
    cfg = json.loads(CONFIG.read_bytes())
    base.require(
        not cfg["economic_runner_enabled_without_separate_admission"]
        and not cfg["goal_verified"]
        and not cfg["live_trading_allowed"]
        and cfg["protected_from"] == "2026-01-01",
        "research scope",
    )
    design = inputs.checked_json(
        base.safe(base.PROJECT, cfg["design"]["path"]), cfg["design"]["sha256"]
    )
    mapping_cfg = inputs.checked_json(
        base.safe(base.PROJECT, cfg["mapper"]["path"]), cfg["mapper"]["sha256"]
    )
    strategy = {k: design[k] for k in ("period", "assets", "signal", "execution")}
    strategy.update(protocol_id=cfg["protocol_id"], screen_gates=cfg["screen_gates"])
    return cfg, strategy, mapping_cfg


def prepared(root, parent, identity):
    base.require(
        root.parent == parent
        and root.resolve() == root
        and root.is_dir()
        and not any(root.iterdir()),
        "prepared empty output leaf; no canonical restart",
    )
    claim = {**identity, "claimed_at_utc": datetime.now(UTC).isoformat()}
    with (root / "started.json").open("x", encoding="utf-8") as stream:
        json.dump(claim, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    return root


def map_source(cfg, mapping_cfg, storage, expected, source_sha):
    source = inputs.checked_json(
        base.safe(storage, cfg["descriptions"]["root"]) / "manifest.json", source_sha
    )
    base.require(
        source["status"] in ("SOURCE_COMPLETE", "COMPLETE_WITH_SOURCE_GAPS")
        and source["planned"]
        == source["processed"]
        == cfg["descriptions"]["expected_descriptions"],
        "closed full description source required before claiming output",
    )
    output = prepared(
        base.safe(storage, cfg["mapping_root"]),
        storage / "source_evidence",
        {"phase": "map", "code_seal_sha256": expected, "source_sha256": source_sha},
    )
    # No OI magnitude column is read in this phase.
    catalog = mapper.load_catalogs(Path(mapping_cfg["catalog_subset_root"]), mapping_cfg)
    base.require(
        catalog.evidence_sha256 == cfg["mapper"]["catalog_evidence_sha256"],
        "catalog evidence drift",
    )
    mapping = inputs.map_closed_descriptions(cfg, storage, source_sha, catalog)
    calendar = inputs.weekly_metadata(cfg, storage)
    mapping.to_parquet(output / "option_contract_mapping.parquet", index=False)
    calendar.to_parquet(output / "release_calendar.parquet", index=False)
    counts = mapping.groupby(["logical_asset", "mapping_reason"], as_index=False).size()
    quality = {
        "inventory_contracts": len(mapping),
        "required_descriptions": int(mapping.needs_description.sum()),
        "metadata_ready_contracts": int(mapping.metadata_ready.sum()),
        "mapping_counts": counts.to_dict("records"),
        "scheduled_asset_dates": len(calendar),
        "source_dates": int(calendar.tradedate.nunique()),
        "empty_scheduled_releases": int(calendar.source_rows.eq(0).sum()),
        "source_rows": int(calendar.source_rows.sum()),
        "original_publication_proved": False,
        "contains_oi_magnitudes_prices_targets_or_pnl": False,
    }
    base.write_json(output / "mapping_quality.json", quality)
    manifest = {
        "protocol_id": cfg["protocol_id"],
        "code_seal_sha256": expected,
        "status": "COMPLETE_STATIC_MAPPING",
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "description_manifest_sha256": source_sha,
        "census_manifest_sha256": cfg["census"]["manifest_sha256"],
        "weekly_manifest_sha256": cfg["source"]["manifest_sha256"],
        "catalog_evidence_sha256": catalog.evidence_sha256,
        "quality": quality,
        "artifacts": {p.name: base.sha(p) for p in sorted(output.iterdir()) if p.is_file()},
        "economic_admission": False,
    }
    base.write_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "mapping_root": str(output),
                "manifest_sha256": base.sha(output / "manifest.json"),
                "quality": quality,
            }
        ),
        flush=True,
    )
    return output


def admission(cfg, storage, code_sha, expected, *, project=base.PROJECT):
    """No numeric file reads here; a still-running description writer is not an admission."""
    path = base.safe(project, cfg["economic_admission_path"])
    base.require(bool(expected) and path.is_file(), "separate economic admission is absent")
    value = inputs.checked_json(path, expected)
    base.require(
        set(value)
        == {
            "protocol_id",
            "code_seal_sha256",
            "description_manifest_sha256",
            "mapping_manifest_sha256",
            "allow_economic_read",
        }
        and value["protocol_id"] == cfg["protocol_id"]
        and value["code_seal_sha256"] == code_sha
        and value["allow_economic_read"] is True,
        "economic admission scope/identity",
    )
    root = base.safe(storage, cfg["mapping_root"])
    manifest = inputs.checked_json(root / "manifest.json", value["mapping_manifest_sha256"])
    base.require(
        manifest["status"] == "COMPLETE_STATIC_MAPPING"
        and manifest["protocol_id"] == cfg["protocol_id"]
        and manifest["code_seal_sha256"] == code_sha
        and manifest["description_manifest_sha256"] == value["description_manifest_sha256"]
        and manifest["weekly_manifest_sha256"] == cfg["source"]["manifest_sha256"]
        and manifest["census_manifest_sha256"] == cfg["census"]["manifest_sha256"]
        and manifest["catalog_evidence_sha256"] == cfg["mapper"]["catalog_evidence_sha256"],
        "economic mapping provenance",
    )
    source = base.safe(storage, cfg["descriptions"]["root"]) / "manifest.json"
    description_manifest = inputs.checked_json(source, value["description_manifest_sha256"])
    base.require(
        description_manifest["status"] in ("SOURCE_COMPLETE", "COMPLETE_WITH_SOURCE_GAPS")
        and description_manifest["processed"] == cfg["descriptions"]["expected_descriptions"],
        "description source no longer closed",
    )
    required = {
        "option_contract_mapping.parquet",
        "release_calendar.parquet",
        "mapping_quality.json",
        "started.json",
    }
    base.require(set(manifest["artifacts"]) == required, "mapping artifact set")
    for name, digest in manifest["artifacts"].items():
        base.require(base.sha(base.safe(root, name)) == digest, "mapping artifact drift")
    quality = manifest["quality"]
    base.require(
        quality["inventory_contracts"] == cfg["census"]["expected_contracts"]
        and quality["required_descriptions"] == cfg["descriptions"]["expected_descriptions"]
        and quality["scheduled_asset_dates"] == cfg["source"]["expected_asset_dates"]
        and quality["source_dates"] == cfg["source"]["expected_source_dates"]
        and quality["source_rows"] == cfg["source"]["processed"]["rows"]
        and quality["contains_oi_magnitudes_prices_targets_or_pnl"] is False,
        "incomplete mapping/calendar coverage",
    )
    for name, rows, columns in (
        ("option_contract_mapping.parquet", quality["inventory_contracts"], inputs.MAPPING_COLUMNS),
        ("release_calendar.parquet", quality["scheduled_asset_dates"], inputs.CALENDAR_COLUMNS),
    ):
        parquet = pq.ParquetFile(root / name)
        base.require(
            parquet.metadata.num_rows == rows and set(parquet.schema_arrow.names) == columns,
            "mapping/calendar physical schema or rows",
        )
    return value, manifest


def assess(metrics, quality, cfg):
    result = reporting.assess(metrics, quality, cfg)
    if (
        not result["checks"]["reported_state_coverage"]
        and result["verdict"] != "INVALID_EXECUTION_NO_PROMOTION"
    ):
        result["verdict"] = "INCOMPLETE_SOURCE_NO_PROMOTION"
    return result


def run_frames(raw, mapping, calendar, active, closes, market, cfg):
    """Same V90 decisions and same integer ledger; tests can supply entirely fake inputs."""
    dates = rule.days(market.session_date)
    base.require(
        dates.between(cfg["period"]["start"], cfg["period"]["end"]).all()
        and cfg["execution"]["initial_cash_rub"] == base.CAPITAL,
        "market period/capital",
    )
    options, assembly_counts = inputs.assemble_options(raw, mapping, calendar)
    release_quality = inputs.release_quality(options, calendar)
    state, targets = rule.build_targets(active, options, closes, cfg)
    observed = calendar.rename(
        columns={
            "tradedate": "source_date",
            "logical_asset": "asset_code",
            "source_rows": "original_release_rows",
        }
    )
    for frame in [state, *targets.values()]:
        counts = frame[["source_date", "asset_code"]].merge(
            observed[["source_date", "asset_code", "original_release_rows"]],
            how="left",
            on=["source_date", "asset_code"],
            validate="many_to_one",
        )
        frame["original_release_rows"] = counts.original_release_rows.to_numpy()
        frame.loc[
            frame.original_release_rows.eq(0) & frame.reason.eq("NO_MAPPED_EXPIRY"), "reason"
        ] = "EMPTY_SCHEDULED_RELEASE"
    quality = {
        **assembly_counts,
        "scheduled_asset_dates": len(calendar),
        "ready_asset_dates": int(release_quality.mapping_ready.sum()),
        "ready_asset_date_fraction": float(release_quality.mapping_ready.mean()),
        "all_market_totals_complete": False,
        "ready_decisions": int(state.ready.sum()),
        "total_asset_decisions": len(state),
        "decision_reason_counts": {str(k): int(v) for k, v in state.reason.value_counts().items()},
    }
    metrics, results = {}, {}
    for arm in rule.ARMS:
        metrics[arm], results[arm] = {}, {}
        for cost, (ticks, fee) in cfg["execution"]["costs"].items():
            execution = cfg["execution"]
            result = base.run_futures_portfolio_ledger(
                market,
                targets[arm],
                base.FuturesPortfolioLedgerConfig(
                    initial_cash=execution["initial_cash_rub"],
                    expected_assets=rule.ASSETS,
                    maximum_gross_notional_multiple=execution["maximum_gross_multiple"],
                    initial_margin_buffer_multiplier=execution["margin_buffer"],
                    maximum_participation=execution["maximum_participation"],
                    slippage_ticks=ticks,
                    fee_multiplier=fee,
                    execution_atomicity="asset",
                    unexecutable_target_policy="cancel_and_clip",
                ),
            )
            metrics[arm][cost] = reporting.summarize(result)
            results[arm][cost] = result
    counts = {
        arm: {
            "asset_decisions": len(t),
            "nonzero_targets": int(t.target_weight.ne(0).sum()),
            "decision_dates": int(t.effective_date.nunique()),
        }
        for arm, t in targets.items()
    }
    return {
        "state": state,
        "targets": targets,
        "results": results,
        "release_quality": release_quality,
        "metrics": metrics,
        "counts": counts,
        "source_quality": quality,
        "assessment": assess(metrics, quality, cfg),
    }


def run_economic(cfg, strategy, storage, code_sha, admission_sha):
    admitted, mapping_manifest = admission(cfg, storage, code_sha, admission_sha)
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    parent = {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}
    preflight = {
        "futures": base.preflight(parent, storage),
        "options": reporting.source_preflight(cfg, storage),
    }
    declared = base.declarations(parent)["recent"]
    root = base.safe(storage, cfg["mapping_root"])
    output = prepared(
        base.safe(storage, "runs/" + cfg["protocol_id"] + "_" + admission_sha[:12]),
        storage / "runs",
        {"phase": "run", "code_seal_sha256": code_sha, "admission_sha256": admission_sha},
    )
    base.write_json(
        output / "inputs.json",
        {
            "admission": admitted,
            "admission_sha256": admission_sha,
            "code_seal_sha256": code_sha,
            "preflight": preflight,
            "mapping_manifest": mapping_manifest,
            "started_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    # This is the first OI/market numeric read, after both independent seals and all preflights.
    raw = pd.read_parquet(
        base.safe(storage, cfg["source"]["root"] + "/" + cfg["source"]["processed"]["path"]),
        columns=sorted(inputs.SOURCE_COLUMNS),
    )
    mapping = pd.read_parquet(root / "option_contract_mapping.parquet")
    calendar = pd.read_parquet(root / "release_calendar.parquet")
    active = pd.read_parquet(
        base.safe(storage, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    obs = pd.read_parquet(
        base.safe(storage, declared["observations"]["path"]), columns=base.OBS_COLS
    )
    specs = pd.read_parquet(
        base.safe(storage, declared["specs"]["path"]), columns=sorted(base.SPEC_PROXY_COLUMNS)
    )
    market = base.build_portfolio_market(
        obs.rename(
            columns={
                "trade_date": "session_date",
                "logical_asset": "asset_code",
                "canonical_contract_id": "contract_id",
            }
        ),
        specs,
    )
    market = market.loc[
        pd.to_datetime(market.session_date).between(
            strategy["period"]["start"], strategy["period"]["end"]
        )
    ]
    result = run_frames(
        raw, mapping, calendar, active, obs[sorted(rule.CLOSE_COLUMNS)], market, strategy
    )
    result["state"].to_parquet(output / "signal_state.parquet", index=False)
    result["release_quality"].to_parquet(output / "release_quality.parquet", index=False)
    for arm, target in result["targets"].items():
        target.to_parquet(output / f"targets_{arm}.parquet", index=False)
        for cost, ledger in result["results"][arm].items():
            for name in ("ledger", "orders", "positions"):
                getattr(ledger, name).to_parquet(
                    output / f"{name}_{arm}_{cost}.parquet", index=False
                )
    report = {k: result[k] for k in ("metrics", "counts", "source_quality", "assessment")}
    report.update(
        protocol_id=cfg["protocol_id"],
        stage=1,
        code_seal_sha256=code_sha,
        admission_sha256=admission_sha,
        completed_at_utc=datetime.now(UTC).isoformat(),
        limitations=cfg["limitations"],
        independent_holdout=False,
        goal_verified=False,
    )
    base.write_json(output / "metrics.json", report)
    base.write_json(
        output / "manifest.json",
        {
            "protocol_id": cfg["protocol_id"],
            "status": "COMPLETE",
            "admission_sha256": admission_sha,
            "artifacts": {p.name: base.sha(p) for p in sorted(output.iterdir()) if p.is_file()},
        },
    )
    print(json.dumps({"output": str(output), "assessment": report["assessment"]}), flush=True)
    return output


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--phase", choices=("map", "run"), required=True)
    cli.add_argument("--source-sha")
    cli.add_argument("--admission-sha")
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "gpu-mlserver service user only")
    base.require(
        (args.phase == "map" and args.source_sha and not args.admission_sha)
        or (args.phase == "run" and args.admission_sha and not args.source_sha),
        "one sealed phase",
    )
    cfg, strategy, mapping_cfg = load_protocol(args.seal_sha)
    storage = Path("/srv/trading_lab_data")
    if args.phase == "map":
        map_source(cfg, mapping_cfg, storage, args.seal_sha, args.source_sha)
    else:
        run_economic(cfg, strategy, storage, args.seal_sha, args.admission_sha)


if __name__ == "__main__":
    main()
