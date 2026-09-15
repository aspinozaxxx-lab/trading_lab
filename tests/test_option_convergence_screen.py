"""Synthetic full pipeline: raw metadata -> releases -> targets -> original ledger."""

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import test_option_contract_mapping as fixture

from market_lab.futures import option_convergence_inputs as inp
from market_lab.futures import option_convergence_screen as screen

rule, mapper = screen.rule, screen.mapper


def config():
    return json.loads(
        (Path(__file__).parents[1] / "configs/v92_option_convergence_screen_v1.json").read_bytes()
    )


def strategy():
    cfg = config()
    design = json.loads((Path(__file__).parents[1] / cfg["design"]["path"]).read_bytes())
    return {**design, "protocol_id": cfg["protocol_id"], "screen_gates": cfg["screen_gates"]}


def fake_inputs():
    rows, mappings, requests, market, active, closes = [], [], [], [], [], []
    catalog = mapper.prepare_catalog(
        pd.concat([fixture.catalog_frame(a) for a in rule.ASSETS], ignore_index=True)
    )
    for asset in rule.ASSETS:
        cid = fixture.catalog_frame(asset).iloc[0].canonical_contract_id
        for strike in (90, 110):
            for side in ("C", "P"):
                fields = fixture.fields(asset, side)
                secid = f"TEST-{asset}-{side}-{strike}"
                for key, value in {
                    "SECID": secid,
                    "STRIKE": str(strike),
                    "LSTTRADE": "2021-01-22",
                    "LSTDELDATE": "2021-01-22",
                }.items():
                    fields[key]["value"] = value
                raw = fixture.raw_bytes(fields)
                bound = mapper.map_description(
                    raw, mapper.digest(raw), secid=secid, logical_asset=asset, catalog=catalog
                )
                mapped = inp.empty_mapping(secid, asset, catalog.evidence_sha256, True)
                mapped.update({k: bound[k] for k in inp.FEATURE_METADATA})
                mapped.update(
                    mapping_reason=bound["reason"],
                    description_sha256=mapper.digest(raw),
                    source_record_sha256="1" * 64,
                )
                mappings.append(mapped)
                for day in pd.to_datetime(["2021-01-08", "2021-01-15"]):
                    rows.append(
                        dict(
                            tradedate=day,
                            logical_asset=asset,
                            secid=secid,
                            boardid="TEST",
                            available_at_utc=(
                                day.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)
                            ).tz_convert("UTC"),
                            option_type={"C": "call", "P": "put"}[side],
                            openposition=50.0 if strike == 90 else 150.0,
                        )
                    )
        for day in ("2021-01-08", "2021-01-15"):
            requests.append(
                dict(
                    query_date=day,
                    server_assetcode=mapper.FUTURES_ASSET_REGISTRY[asset][0],
                    start=0,
                )
            )
        days = pd.bdate_range("2021-01-08", "2021-01-25")
        for decision, effective in zip(days[:-1], days[1:], strict=True):
            active.append(
                dict(
                    decision_date=decision,
                    effective_date=effective,
                    observed_through=decision,
                    asset_code=asset,
                    contract_id=cid,
                    plan_tradable=True,
                    roll=False,
                )
            )
        for day in days:
            closes.append(
                dict(trade_date=day, logical_asset=asset, canonical_contract_id=cid, close=98.0)
            )
            market.append(
                dict(
                    session_date=day,
                    asset_code=asset,
                    contract_id=cid,
                    open=98.0,
                    high=98.0,
                    low=98.0,
                    settle=98.0,
                    volume=1_000_000.0,
                    sizing_point_value=100.0,
                    accounting_point_value=100.0,
                    tick_size=0.01,
                    fee_per_contract=1.0,
                    initial_margin=500.0,
                )
            )
    raw, mapping = pd.DataFrame(rows), pd.DataFrame(mappings)
    cfg = config()
    cfg["source"].update(expected_asset_dates=8, expected_source_dates=2)
    cfg["source"]["processed"].update(
        minimum_tradedate="2021-01-08", maximum_tradedate="2021-01-15"
    )
    calendar = inp.source_calendar(requests, raw[sorted(inp.SOURCE_METADATA)], cfg)
    return (
        raw,
        mapping,
        calendar,
        pd.DataFrame(active),
        pd.DataFrame(closes),
        pd.DataFrame(market),
        requests,
        cfg,
    )


def execute(parts=None):
    parts = fake_inputs() if parts is None else parts
    return screen.run_frames(*parts[:6], strategy())


def test_full_fake_source_to_ledger_both_arms_and_costs():
    parts = fake_inputs()
    result = execute(parts)
    assert result["source_quality"]["ready_asset_date_fraction"] == 1.0
    assert result["source_quality"]["original_source_rows"] == 32
    assert result["source_quality"]["empty_release_markers"] == 0
    assert len(result["state"]) == len(parts[3])
    for arm, costs in result["metrics"].items():
        assert set(costs) == {"base", "double"}
        for value in costs.values():
            assert value["round_trips"] > 0 and value["cagr"] < 0
            assert value["execution_complete"] and not value["terminal_carried"]
            assert value["unresolved_halt_count"] == value["critical_failure_count"] == 0
        assert costs["double"]["ending_cash"] < costs["base"]["ending_cash"]
        assert result["targets"][arm].groupby("asset_code").tail(1).target_weight.eq(0).all()
    assert result["assessment"]["verdict"] == "REJECT_STAGE1"
    assert not result["assessment"]["goal_verified"]


def test_empty_latest_scheduled_release_replaces_old_signal_without_zero_oi():
    parts = list(fake_inputs())
    parts[0] = parts[0].loc[
        ~(parts[0].logical_asset.eq("SI") & parts[0].tradedate.eq("2021-01-15"))
    ]
    parts[2] = inp.source_calendar(parts[6], parts[0][sorted(inp.SOURCE_METADATA)], parts[7])
    joined, counts = inp.assemble_options(*parts[:3])
    marker = joined.loc[joined.boardid.eq(inp.MARKER)]
    assert counts["empty_release_markers"] == 1 and counts["original_source_rows"] == 28
    assert len(marker) == 1 and marker.openposition.isna().all()
    assert not marker.metadata_ready.any() and marker.available_at_utc.notna().all()
    result = execute(parts)
    row = (
        result["state"]
        .loc[lambda x: x.asset_code.eq("SI") & x.decision_date.eq("2021-01-18")]
        .iloc[0]
    )
    assert row.source_date == pd.Timestamp("2021-01-15")
    assert row.reason == "EMPTY_SCHEDULED_RELEASE" and row.original_release_rows == 0
    target = result["targets"]["primary"].loc[
        lambda x: x.asset_code.eq("SI") & x.decision_date.eq("2021-01-18")
    ]
    assert target.target_weight.eq(0).all()
    assert result["source_quality"]["ready_asset_date_fraction"] == 7 / 8


def test_all_null_and_zero_trades_keep_complete_calendar():
    parts = list(fake_inputs())
    parts[0]["openposition"] = np.nan
    result = execute(parts)
    assert len(result["state"]) == len(parts[3]) and len(result["release_quality"]) == 8
    assert result["assessment"]["verdict"] == "INCOMPLETE_SOURCE_NO_PROMOTION"
    for arm, costs in result["metrics"].items():
        assert result["targets"][arm].target_weight.eq(0).all()
        assert all(v["round_trips"] == 0 and v["net_pnl"] == 0 for v in costs.values())


def test_entirely_empty_source_produces_eight_explicit_unavailable_releases():
    parts = list(fake_inputs())
    parts[0] = parts[0].iloc[:0]
    parts[2] = inp.source_calendar(parts[6], parts[0][sorted(inp.SOURCE_METADATA)], parts[7])
    result = execute(parts)
    assert result["source_quality"]["original_source_rows"] == 0
    assert result["source_quality"]["empty_release_markers"] == 8
    assert not result["state"].ready.any() and len(result["state"]) == len(parts[3])


def test_side_conflict_masks_only_affected_release_without_old_good_fallback():
    parts = list(fake_inputs())
    mask = parts[0].secid.eq("TEST-SI-C-90") & parts[0].tradedate.eq("2021-01-15")
    parts[0].loc[mask, "option_type"] = "put"
    options, counts = inp.assemble_options(*parts[:3])
    state, _ = rule.build_targets(parts[3], options, parts[4], strategy())
    rows = state.loc[state.decision_date.eq("2021-01-18")]
    assert counts["source_side_conflict_rows"] == 1
    assert rows.loc[rows.asset_code.eq("SI"), "reason"].eq("UNRESOLVED_REPORTED_METADATA").all()
    assert rows.loc[rows.asset_code.ne("SI"), "ready"].all()


def test_modifying_future_release_does_not_change_earlier_targets():
    parts = list(fake_inputs())
    original, _ = inp.assemble_options(*parts[:3])
    _, a = rule.build_targets(parts[3], original, parts[4], strategy())
    parts[0].loc[parts[0].tradedate.eq("2021-01-15"), "openposition"] = np.nan
    changed, _ = inp.assemble_options(*parts[:3])
    _, b = rule.build_targets(parts[3], changed, parts[4], strategy())
    for arm in rule.ARMS:
        left = a[arm].loc[a[arm].decision_date.lt("2021-01-16")]
        right = b[arm].loc[b[arm].decision_date.lt("2021-01-16")]
        pd.testing.assert_frame_equal(left, right)


@pytest.mark.parametrize(
    "mutation", ["missing_request", "protected", "extra_asset", "mixed_clock", "label", "duplicate"]
)
def test_source_calendar_guards(mutation):
    raw, _, _, _, _, _, requests, cfg = fake_inputs()
    metadata = raw[sorted(inp.SOURCE_METADATA)].copy()
    if mutation == "missing_request":
        requests = requests[:-1]
    elif mutation == "protected":
        requests[0]["query_date"] = "2026-01-01"
    elif mutation == "extra_asset":
        requests[0]["server_assetcode"] = "GOLD"
    elif mutation == "mixed_clock":
        metadata.loc[0, "available_at_utc"] += pd.Timedelta(hours=1)
    elif mutation == "label":
        metadata["future_return"] = 1.0
    else:
        metadata = pd.concat([metadata, metadata.iloc[:1]], ignore_index=True)
    with pytest.raises(ValueError):
        inp.source_calendar(requests, metadata, cfg)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_map",
        "duplicate_map",
        "manual_flag",
        "extra_price",
        "wrong_count",
        "wrong_clock",
        "missing_calendar_asset",
    ],
)
def test_assembly_rejects_drift(mutation):
    raw, mapping, calendar, *_ = fake_inputs()
    if mutation == "missing_map":
        mapping = mapping.iloc[1:]
    elif mutation == "duplicate_map":
        mapping = pd.concat([mapping, mapping.iloc[:1]], ignore_index=True)
    elif mutation == "manual_flag":
        mapping["metadata_ready"] = "True"
    elif mutation == "extra_price":
        raw["close"] = 98.0
    elif mutation == "wrong_count":
        calendar.loc[0, "source_rows"] += 1
    elif mutation == "wrong_clock":
        calendar.loc[0, "available_at_utc"] += pd.Timedelta(hours=1)
    else:
        calendar = calendar.iloc[1:]
    with pytest.raises(ValueError):
        inp.assemble_options(raw, mapping, calendar)


def test_protected_market_rejected_before_ledger(monkeypatch):
    parts = list(fake_inputs())
    parts[5].loc[0, "session_date"] = pd.Timestamp("2026-01-01")
    monkeypatch.setattr(
        screen.base, "run_futures_portfolio_ledger", lambda *a, **k: pytest.fail("ledger invoked")
    )
    with pytest.raises(ValueError, match="protected"):
        execute(parts)


def green_metrics():
    base = dict(
        execution_complete=True,
        critical_failure_count=0,
        unresolved_halt_count=0,
        terminal_carried=False,
        round_trips=50,
        cagr=0.1,
        sharpe=0.8,
        maximum_drawdown=0.1,
        positive_years=4,
        worst_year=-0.01,
        annual_returns={str(y): 0.1 for y in range(2021, 2026)},
    )
    return {
        "primary": {"base": copy.deepcopy(base), "double": copy.deepcopy(base)},
        "control": {"base": {**base, "cagr": 0.01}, "double": {**base, "cagr": 0.01}},
    }


def test_even_fifty_percent_fake_metrics_never_verify_goal():
    values = green_metrics()
    for value in values["primary"].values():
        value["cagr"] = 0.6
    out = screen.assess(values, {"ready_asset_date_fraction": 1.0}, strategy())
    assert out["verdict"] == "STAGE2_CANDIDATE" and out["historical_50_percent_each_cost"]
    assert not out["goal_verified"]


@pytest.mark.parametrize(
    "mutation",
    ["coverage", "critical", "zero_trades", "missing_year", "control_wins", "missing_cost"],
)
def test_predeclared_gates(mutation):
    metrics = green_metrics()
    quality = {"ready_asset_date_fraction": 1.0}
    if mutation == "coverage":
        quality["ready_asset_date_fraction"] = 0.79
    elif mutation == "critical":
        metrics["control"]["double"]["critical_failure_count"] = 1
    elif mutation == "zero_trades":
        metrics["primary"]["double"]["round_trips"] = 0
    elif mutation == "missing_year":
        metrics["primary"]["double"]["annual_returns"].pop("2022")
    elif mutation == "control_wins":
        metrics["control"]["double"]["cagr"] = 0.2
    else:
        metrics["control"].pop("double")
        with pytest.raises(ValueError, match="missing cost"):
            screen.assess(metrics, quality, strategy())
        return
    out = screen.assess(metrics, quality, strategy())
    expected = {
        "coverage": "INCOMPLETE_SOURCE_NO_PROMOTION",
        "critical": "INVALID_EXECUTION_NO_PROMOTION",
    }
    assert out["verdict"] == expected.get(mutation, "REJECT_STAGE1")
    assert not out["goal_verified"]


def put_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return mapper.digest(path.read_bytes())


def fake_closed_source(tmp_path, *, http_status=200, reuse=False):
    cfg = config()
    source = tmp_path / cfg["descriptions"]["root"]
    old = tmp_path / cfg["descriptions"]["reuse_root"]
    source.mkdir(parents=True)
    old.mkdir(parents=True)
    cfg["descriptions"]["reuse_manifest_sha256"] = put_json(old / "manifest.json", {"fake": True})
    cfg["descriptions"]["expected_descriptions"] = 1
    cfg["census"]["expected_contracts"] = 2
    plan = pd.DataFrame(
        [
            dict(
                logical_asset="SI",
                secid="TEST-SI-C",
                first_seen=pd.Timestamp("2021-01-08"),
                last_seen=pd.Timestamp("2021-01-15"),
                needs_description=True,
            ),
            dict(
                logical_asset="SI",
                secid="ALL-NULL",
                first_seen=pd.Timestamp("2021-01-08"),
                last_seen=pd.Timestamp("2021-01-15"),
                needs_description=False,
            ),
        ]
    )
    census_root = tmp_path / cfg["census"]["root"]
    census_root.mkdir(parents=True)
    plan.to_parquet(census_root / "contracts.parquet", index=False)
    cfg["census"]["contracts_sha256"] = screen.base.sha(census_root / "contracts.parquet")
    census = {
        "seal_sha256": cfg["descriptions"]["source_seal_sha256"],
        "artifacts": {"contracts.parquet": cfg["census"]["contracts_sha256"]},
    }
    cfg["census"]["manifest_sha256"] = put_json(census_root / "manifest.json", census)
    raw = fixture.raw_bytes(fixture.fields())
    raw_path = (old if reuse else source) / "response.raw"
    raw_path.write_bytes(raw)
    spec = dict(path=str(raw_path), bytes=len(raw), sha256=mapper.digest(raw))
    if reuse:
        spec["source_manifest_sha256"] = cfg["descriptions"]["reuse_manifest_sha256"]
    record = dict(
        kind="description",
        identity={"secid": "TEST-SI-C", "asset": "SI"},
        url=cfg["descriptions"]["url"].format(secid="TEST-SI-C"),
        reference_reused=reuse,
        raw=spec,
        attempts=[{"http_status": http_status}],
    )
    record_sha = put_json(source / "record.json", record)
    manifest = dict(
        status="SOURCE_COMPLETE",
        processed=1,
        planned=1,
        seal_sha256=cfg["descriptions"]["source_seal_sha256"],
        census_manifest_sha256=cfg["census"]["manifest_sha256"],
        economic_admission=False,
        completed_at_utc="2026-09-15T00:00:00Z",
        records=[
            dict(logical_asset="SI", secid="TEST-SI-C", record="record.json", sha256=record_sha)
        ],
    )
    source_sha = put_json(source / "manifest.json", manifest)
    return cfg, source_sha, mapper.prepare_catalog(fixture.catalog_frame()), manifest, plan


@pytest.mark.parametrize("reuse", [False, True])
def test_closed_source_maps_each_needed_identity_and_preserves_all_null(tmp_path, reuse):
    cfg, source_sha, catalog, _, _ = fake_closed_source(tmp_path, reuse=reuse)
    mapped = inp.map_closed_descriptions(cfg, tmp_path, source_sha, catalog)
    assert len(mapped) == 2 and set(mapped.columns) == inp.MAPPING_COLUMNS
    assert mapped.iloc[0].metadata_ready and mapped.iloc[0].mapping_reason == "EXACT_STATIC_BINDING"
    assert (
        not mapped.iloc[1].metadata_ready
        and mapped.iloc[1].mapping_reason == "ALL_NULL_NOT_REQUESTED"
    )


def test_http_error_is_not_mapped_even_if_body_looks_like_valid_description(tmp_path):
    cfg, source_sha, catalog, _, _ = fake_closed_source(tmp_path, http_status=503)
    mapped = inp.map_closed_descriptions(cfg, tmp_path, source_sha, catalog)
    assert mapped.iloc[0].mapping_reason == "DESCRIPTION_SOURCE_UNAVAILABLE"
    assert not mapped.iloc[0].metadata_ready and len(mapped) == 2


@pytest.mark.parametrize(
    "mutation", ["running", "count", "wrong_key", "duplicate", "wrong_seal", "wrong_census"]
)
def test_partial_or_wrong_description_index_rejected(tmp_path, mutation):
    cfg, _, _, manifest, plan = fake_closed_source(tmp_path)
    if mutation == "running":
        manifest["status"] = "RUNNING"
    elif mutation == "count":
        manifest["processed"] = 0
    elif mutation == "wrong_key":
        manifest["records"][0]["secid"] = "OTHER"
    elif mutation == "duplicate":
        manifest["records"] *= 2
    elif mutation == "wrong_seal":
        manifest["seal_sha256"] = "0" * 64
    else:
        manifest["census_manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        inp.closed_index(manifest, plan, cfg)


def test_raw_tampering_is_not_silently_counted_as_source_unavailable(tmp_path):
    cfg, source_sha, catalog, _, _ = fake_closed_source(tmp_path)
    (tmp_path / cfg["descriptions"]["root"] / "response.raw").write_bytes(b"changed")
    with pytest.raises(ValueError, match="raw drift"):
        inp.map_closed_descriptions(cfg, tmp_path, source_sha, catalog)


def test_no_economic_admission_means_no_numeric_reader_invocation(tmp_path, monkeypatch):
    cfg = config()
    cfg["economic_admission_path"] = str(tmp_path / "absent.json")
    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: pytest.fail("numeric reader invoked"))
    # The unsafe path is rejected even earlier than a missing relative admission.
    with pytest.raises(ValueError):
        screen.run_economic(cfg, strategy(), tmp_path, "1" * 64, "2" * 64)
    cfg["economic_admission_path"] = "absent.json"
    with pytest.raises(ValueError, match="admission is absent"):
        screen.run_economic(cfg, strategy(), tmp_path, "1" * 64, "2" * 64)
    with pytest.raises(ValueError, match="admission is absent"):
        screen.admission(cfg, tmp_path, "1" * 64, "2" * 64, project=tmp_path)


def test_false_economic_admission_is_not_permission(tmp_path):
    cfg = config()
    value = dict(
        protocol_id=cfg["protocol_id"],
        code_seal_sha256="1" * 64,
        description_manifest_sha256="2" * 64,
        mapping_manifest_sha256="3" * 64,
        allow_economic_read=False,
    )
    sha = put_json(tmp_path / cfg["economic_admission_path"], value)
    with pytest.raises(ValueError, match="scope/identity"):
        screen.admission(cfg, tmp_path, "1" * 64, sha, project=tmp_path)


def test_output_claim_is_exclusive_and_preserves_partial_work(tmp_path):
    root = tmp_path / "new-leaf"
    root.mkdir()
    screen.prepared(root, tmp_path, {"phase": "synthetic"})
    before = (root / "started.json").read_bytes()
    with pytest.raises(ValueError, match="no canonical restart"):
        screen.prepared(root, tmp_path, {"phase": "synthetic"})
    assert (root / "started.json").read_bytes() == before


def test_mapping_phase_rejects_running_source_before_claiming_output(tmp_path, monkeypatch):
    cfg, _, _, manifest, _ = fake_closed_source(tmp_path)
    manifest["status"] = "RUNNING"
    sha = put_json(tmp_path / cfg["descriptions"]["root"] / "manifest.json", manifest)
    monkeypatch.setattr(
        mapper, "load_catalogs", lambda *a, **k: pytest.fail("catalog loader invoked")
    )
    with pytest.raises(ValueError, match="closed full"):
        screen.map_source(cfg, {}, tmp_path, "1" * 64, sha)
    assert not (tmp_path / cfg["mapping_root"]).exists()


def published_fake_mapping(tmp_path, monkeypatch):
    cfg, source_sha, catalog, _, _ = fake_closed_source(tmp_path)
    cfg["mapper"]["catalog_evidence_sha256"] = catalog.evidence_sha256
    calendar = fake_inputs()[2]
    calendar["source_rows"] = np.where(calendar.logical_asset.eq("SI"), 2, 0)
    cfg["source"].update(expected_source_dates=2, expected_asset_dates=8)
    cfg["source"]["processed"]["rows"] = 4
    root = tmp_path / cfg["mapping_root"]
    root.mkdir()
    monkeypatch.setattr(mapper, "load_catalogs", lambda *a, **k: catalog)
    monkeypatch.setattr(inp, "weekly_metadata", lambda *a, **k: calendar)
    screen.map_source(cfg, {"catalog_subset_root": str(tmp_path)}, tmp_path, "1" * 64, source_sha)
    mapping_sha = screen.base.sha(root / "manifest.json")
    card = dict(
        protocol_id=cfg["protocol_id"],
        code_seal_sha256="1" * 64,
        description_manifest_sha256=source_sha,
        mapping_manifest_sha256=mapping_sha,
        allow_economic_read=True,
    )
    card_sha = put_json(tmp_path / cfg["economic_admission_path"], card)
    return cfg, card, card_sha


def test_mapping_outputs_and_separate_admission_bind_full_artifacts(tmp_path, monkeypatch):
    cfg, card, sha = published_fake_mapping(tmp_path, monkeypatch)
    admitted, manifest = screen.admission(cfg, tmp_path, "1" * 64, sha, project=tmp_path)
    assert admitted == card and manifest["quality"]["inventory_contracts"] == 2
    assert set(manifest["artifacts"]) == {
        "started.json",
        "option_contract_mapping.parquet",
        "release_calendar.parquet",
        "mapping_quality.json",
    }
    assert not manifest["economic_admission"]


@pytest.mark.parametrize(
    "mutation",
    ["missing_artifact", "artifact_drift", "wrong_code", "partial_quality", "wrong_source"],
)
def test_economic_admission_rejects_partial_or_mismatched_bindings(tmp_path, monkeypatch, mutation):
    cfg, card, sha = published_fake_mapping(tmp_path, monkeypatch)
    root = tmp_path / cfg["mapping_root"]
    manifest = json.loads((root / "manifest.json").read_bytes())
    if mutation == "missing_artifact":
        manifest["artifacts"].pop("release_calendar.parquet")
    elif mutation == "artifact_drift":
        (root / "release_calendar.parquet").write_bytes(b"tampered")
    elif mutation == "wrong_code":
        manifest["code_seal_sha256"] = "9" * 64
    elif mutation == "partial_quality":
        manifest["quality"]["scheduled_asset_dates"] = 7
    else:
        manifest["description_manifest_sha256"] = "9" * 64
    card["mapping_manifest_sha256"] = put_json(root / "manifest.json", manifest)
    sha = put_json(tmp_path / cfg["economic_admission_path"], card)
    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: pytest.fail("numeric reader invoked"))
    with pytest.raises(ValueError):
        screen.admission(cfg, tmp_path, "1" * 64, sha, project=tmp_path)
