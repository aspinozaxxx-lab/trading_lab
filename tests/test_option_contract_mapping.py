"""Synthetic metadata only: exact expiry, aliases, SI currency and raw-unit evidence."""

import copy
import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import option_contract_mapping as m
from market_lab.futures import option_strike_convergence as signal


def catalog_frame(asset="SI", year=2021, expiry="2021-03-18"):
    official, prefix = m.FUTURES_ASSET_REGISTRY[asset]
    code = f"{prefix}H{year % 10}"
    return pd.DataFrame([dict(
        canonical_contract_id=f"{official}:{code}:{expiry}", secid=code,
        name=f"{official}-3.{year % 100:02d}", start_date=f"{year - 1}-01-01",
        expiration_date=expiry, asset_code=official,
        underlying_asset="USD000UTSTOM" if asset == "SI" else None,
    )])


def fields(asset="SI", side="C"):
    row = catalog_frame(asset).iloc[0]
    values = dict(
        SECID=f"TEST-{asset}-{side}", ASSETCODE=row.asset_code, TYPE="option",
        GROUP="futures_options", MARGINSTYLE="Маржируемый", FRSTTRADE="2020-12-01",
        LSTTRADE="2021-03-18", LSTDELDATE="2021-03-18", STRIKE="98", LOTSIZE="1",
        OPTIONTYPE=side, UNIT="synthetic premium unit, not the strike quote",
        EXECTYPE="Американский", SERIES_NAME=row["name"] + "M180321XA",
        NAME="Synthetic option на фьюч. контр. " + row["name"],
        UNDERLYINGASSET="USD000UTSTOM" if asset == "SI" else row.secid,
        DELIVERYTYPE="Synthetic contract. " + m.STRIKE_DELIVERY,
    )
    return {key: {"name": key, "value": value,
                  "type": "date" if key in ("FRSTTRADE", "LSTTRADE", "LSTDELDATE")
                  else "number" if key in ("STRIKE", "LOTSIZE") else "string",
                  "title": "Цена Страйк" if key == "STRIKE"
                  else "Дата экспирации" if key == "LSTDELDATE" else key}
            for key, value in values.items()}


def raw_bytes(d):
    return json.dumps({"description": {"columns": ["name", "value", "type", "title"],
                                      "data": [[r[k] for k in ("name", "value", "type", "title")]
                                               for r in d.values()]}}, ensure_ascii=False).encode()


def mapped(d=None, frame=None, asset="SI", side="C"):
    d = fields(asset, side) if d is None else d
    raw = raw_bytes(d)
    catalog = m.prepare_catalog(catalog_frame(asset) if frame is None else frame)
    return m.map_description(raw, m.digest(raw), secid=f"TEST-{asset}-{side}",
                             logical_asset=asset, catalog=catalog)


@pytest.mark.parametrize("asset", ["SI", "RI", "BR", "MIX"])
@pytest.mark.parametrize("side", ["C", "P"])
def test_exact_binding_all_assets_and_sides(asset, side):
    out = mapped(asset=asset, side=side)
    assert out["metadata_ready"] and out["quote_units_compatible"]
    assert out["reason"] == "EXACT_STATIC_BINDING"
    assert out["underlying_contract_id"] == catalog_frame(asset).iloc[0].canonical_contract_id
    assert out["option_type"] == {"C": "call", "P": "put"}[side]
    assert out["strike"] == 98 and out["strike_price_equality_proved"]
    assert not out["economic_admission"] and not out["original_publication_proved"]
    assert ("SI_CASH_ROOT" in out["underlying_binding"]) == (asset == "SI")


def test_currency_product_excluded_even_with_same_si_cash_root():
    d = fields()
    d["TYPE"]["value"], d["MARGINSTYLE"]["value"] = "option_on_currency", "Премиальный"
    d["DELIVERYTYPE"]["value"] = "Synthetic cash settlement at currency fixing."
    out = mapped(d)
    assert out["metadata_ready"] and out["option_class"] == "premium_currency_option"
    assert out["reason"] == "EXCLUDED_PREMIUM_CURRENCY"
    assert out["underlying_contract_id"] is None and not out["quote_units_compatible"]


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("SECID", "OTHER", "OPTION_IDENTITY_MISMATCH"),
    ("ASSETCODE", "RTS", "OPTION_ASSET_OR_GROUP_MISMATCH"),
    ("GROUP", "equities", "OPTION_ASSET_OR_GROUP_MISMATCH"),
    ("TYPE", "unknown", "UNSUPPORTED_OPTION_CLASS"),
    ("MARGINSTYLE", "Премиальный", "UNSUPPORTED_OPTION_CLASS"),
    ("FRSTTRADE", "2021-03-19", "INVALID_EXPLICIT_LIFECYCLE"),
    ("LSTTRADE", "2021-03-19", "INVALID_EXPLICIT_LIFECYCLE"),
    ("LSTDELDATE", "2021-03-18T00:00:00", "INVALID_EXPLICIT_LIFECYCLE"),
    ("LSTDELDATE", "2021-02-30", "INVALID_EXPLICIT_LIFECYCLE"),
    ("STRIKE", "nan", "INVALID_STRIKE_OR_CONTRACT_FIELDS"),
    ("STRIKE", "inf", "INVALID_STRIKE_OR_CONTRACT_FIELDS"),
    ("STRIKE", "-1", "INVALID_STRIKE_OR_CONTRACT_FIELDS"),
    ("STRIKE", True, "INVALID_STRIKE_OR_CONTRACT_FIELDS"),
    ("LOTSIZE", "0", "INVALID_STRIKE_OR_CONTRACT_FIELDS"),
    ("UNIT", "", "INVALID_STRIKE_OR_CONTRACT_FIELDS"),
    ("EXECTYPE", "unknown", "INVALID_STRIKE_OR_CONTRACT_FIELDS"),
    ("OPTIONTYPE", "X", "INVALID_STRIKE_OR_CONTRACT_FIELDS"),
    ("OPTIONTYPE", [], "INVALID_STRIKE_OR_CONTRACT_FIELDS"),
    ("SERIES_NAME", "Si-6.21M180321XA", "UNDERLYING_NAME_MISSING"),
    ("NAME", "Synthetic на фьюч. контр. Si-3.21 plus another", "UNDERLYING_NAME_MISSING"),
    ("UNDERLYINGASSET", "SiM1", "UNDERLYING_FIELD_CONFLICT"),
    ("UNDERLYINGASSET", [], "UNDERLYING_FIELD_CONFLICT"),
    ("DELIVERYTYPE", "При исполнении опциона НЕ заключается фьючерс.",
     "STRIKE_TO_FUTURES_PRICE_NOT_PROVED"),
])
def test_unknown_or_conflicting_fields_never_become_ready(field, value, reason):
    d = fields()
    d[field]["value"] = value
    out = mapped(d)
    assert out["reason"] == reason
    assert not out["metadata_ready"] and not out["quote_units_compatible"]


@pytest.mark.parametrize(("field", "key", "value", "reason"), [
    ("LSTDELDATE", "title", "Last trading date", "INVALID_EXPLICIT_LIFECYCLE"),
    ("LSTDELDATE", "type", "string", "INVALID_EXPLICIT_LIFECYCLE"),
    ("STRIKE", "title", "Premium", "INVALID_STRIKE_OR_CONTRACT_FIELDS"),
    ("STRIKE", "type", "string", "INVALID_STRIKE_OR_CONTRACT_FIELDS"),
])
def test_expiry_and_strike_require_explicit_definitions(field, key, value, reason):
    d = fields()
    d[field][key] = value
    assert mapped(d)["reason"] == reason


def test_premium_unit_is_not_used_as_a_strike_multiplier():
    d = fields()
    d["UNIT"]["value"] = "synthetic premium per 1000 lots"
    d["LOTSIZE"]["value"] = "1000"
    out = mapped(d)
    assert out["quote_units_compatible"] and out["strike"] == 98
    d["DELIVERYTYPE"]["value"] = ""
    assert not mapped(d)["quote_units_compatible"]


def test_html_and_spacing_in_delivery_do_not_change_price_equality():
    d = fields()
    d["DELIVERYTYPE"]["value"] = "<br> " + m.STRIKE_DELIVERY.replace(" ", "&nbsp;  ")
    assert mapped(d)["strike_price_equality_proved"]


def test_aliases_of_same_canonical_contract_are_not_ambiguity():
    frame = catalog_frame()
    alias = frame.iloc[0].to_dict()
    alias.update(secid="SiH1_2021", start_date="2019-01-01")
    frame = pd.concat([frame, pd.DataFrame([alias])], ignore_index=True)
    assert mapped(frame=frame)["metadata_ready"]


def test_ambiguous_name_is_not_resolved_by_choosing_first_or_active_contract():
    frame = pd.concat([catalog_frame(), catalog_frame(year=2031, expiry="2031-03-18")],
                      ignore_index=True)
    frame.loc[1, "name"] = "Si-3.21"
    out = mapped(frame=frame)
    assert out["reason"] == "AMBIGUOUS_UNDERLYING_NAME" and not out["metadata_ready"]


def test_recycled_short_code_uses_catalog_name_and_exact_date():
    frame = pd.concat([catalog_frame(), catalog_frame(year=2031, expiry="2031-03-18")],
                      ignore_index=True)
    assert mapped(frame=frame)["underlying_contract_id"] == "Si:SiH1:2021-03-18"


@pytest.mark.parametrize("key", ["start_date", "expiration_date"])
def test_option_cannot_outlive_or_precede_underlying(key):
    frame = catalog_frame()
    frame.loc[0, key] = "2021-01-01"
    if key == "expiration_date":
        frame.loc[0, "canonical_contract_id"] = "Si:SiH1:2021-01-01"
    assert mapped(frame=frame)["reason"] == "UNDERLYING_LIFECYCLE_CONFLICT"


def test_si_cash_root_requires_independent_catalog_agreement():
    frame = catalog_frame()
    frame.loc[0, "underlying_asset"] = "SOMETHING_ELSE"
    assert mapped(frame=frame)["reason"] == "UNDERLYING_FIELD_CONFLICT"


def test_hash_mismatch_aborts_instead_of_counting_a_source_gap():
    with pytest.raises(ValueError, match="hash mismatch"):
        m.map_description(raw_bytes(fields()), "0" * 64, secid="TEST-SI-C",
                          logical_asset="SI", catalog=m.prepare_catalog(catalog_frame()))


@pytest.mark.parametrize("mutation", ["price_block", "duplicate_field", "row_length", "non_json"])
def test_malformed_description_never_ready(mutation):
    payload = json.loads(raw_bytes(fields()))
    if mutation == "price_block":
        payload["marketdata"] = {}
    elif mutation == "duplicate_field":
        payload["description"]["data"].append(payload["description"]["data"][0])
    elif mutation == "row_length":
        payload["description"]["data"][0].append("unexpected")
    raw = b"not json" if mutation == "non_json" else json.dumps(payload).encode()
    out = m.map_description(raw, m.digest(raw), secid="TEST-SI-C", logical_asset="SI",
                            catalog=m.prepare_catalog(catalog_frame()))
    assert out["reason"] == "MALFORMED_DESCRIPTION" and not out["metadata_ready"]


@pytest.mark.parametrize("mutation", ["canonical", "duplicate", "is_traded", "price", "intraday"])
def test_catalog_identity_and_metadata_only_schema(mutation):
    frame = catalog_frame()
    if mutation == "canonical":
        frame.loc[0, "canonical_contract_id"] = "Si:SiH1:2021-03-17"
    elif mutation == "duplicate":
        frame = pd.concat([frame, frame], ignore_index=True)
    elif mutation == "intraday":
        frame.loc[0, "start_date"] = "2020-01-01T12:00:00"
    else:
        frame[mutation] = 1
    with pytest.raises(ValueError):
        m.prepare_catalog(frame)


def test_mapper_output_enters_existing_v90_schema_without_manual_ready_flags():
    rows = []
    source_columns = {"tradedate", "available_at_utc", "boardid", "openposition"}
    for asset in signal.ASSETS:
        out = mapped(asset=asset)
        row = {k: out[k] for k in signal.OPTION_COLUMNS - source_columns}
        row.update(tradedate="2021-03-12", available_at_utc="2021-03-12T21:00:00Z",
                   boardid="SYNTHETIC", openposition=10.0)
        rows.append(row)
    prepared, releases = signal.prepare_options(pd.DataFrame(rows))
    assert prepared.mapping_ok.all() and len(releases) == 4


def static_files(tmp_path):
    """Only generated fake catalogs; no actual market files or network in tests."""
    config = {"catalogs": {}}
    for asset in m.FUTURES_ASSET_REGISTRY:
        frame = catalog_frame(asset)
        columns = [c for c in m.CATALOG_COLUMNS if c != "canonical_contract_id"] + ["is_traded"]
        raw_frame = frame.drop(columns="canonical_contract_id").copy()
        raw_frame["is_traded"] = 0
        payload = {"requests": [{
            "url": "https://iss.moex.com/iss/statistics/engines/futures/markets/forts/series.json?fake",
            "payload": {"series": {"columns": columns,
                                    "data": raw_frame[columns].values.tolist()}},
        }]}
        packed = gzip.compress(json.dumps(payload).encode())
        path = tmp_path / f"{asset}.json.gz"
        path.write_bytes(packed)
        raw_spec = {"path": path.name, "bytes": len(packed), "sha256": m.digest(packed)}
        frame["is_traded"] = False
        path = tmp_path / f"{asset}.parquet"
        frame.to_parquet(path, index=False)
        raw = path.read_bytes()
        pq_spec = {"path": path.name, "bytes": len(raw), "sha256": m.digest(raw), "rows": 1}
        manifest = dict(asset=dict(asset_code=m.FUTURES_ASSET_REGISTRY[asset][0],
                                   logical_symbol=asset), requested_start="2018-01-01",
                        requested_end="2025-12-31", protected_from="2026-01-01",
                        catalog_artifacts={"series": {"raw": raw_spec, "parquet": pq_spec}})
        raw = json.dumps(manifest).encode()
        path = tmp_path / f"{asset}.manifest.json"
        path.write_bytes(raw)
        config["catalogs"][asset] = {
            "manifest": {"path": path.name, "bytes": len(raw), "sha256": m.digest(raw)},
            "raw": raw_spec, "parquet": pq_spec,
        }
    return config


def test_catalog_loader_binds_raw_parquet_and_manifest_without_current_trade_filter(tmp_path):
    cfg = static_files(tmp_path)
    catalog = m.load_catalogs(tmp_path, cfg)
    assert len(catalog.rows) == 4 and len(catalog.sources) == 4
    assert mapped(frame=pd.DataFrame(catalog.rows))["metadata_ready"]


def test_catalog_loader_rejects_drift_and_path_escape(tmp_path):
    cfg = static_files(tmp_path)
    broken = copy.deepcopy(cfg)
    broken["catalogs"]["SI"]["manifest"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="drift"):
        m.load_catalogs(tmp_path, broken)
    broken["catalogs"]["SI"]["manifest"]["path"] = "../outside.json"
    with pytest.raises(ValueError, match="escape"):
        m.load_catalogs(tmp_path, broken)


def test_raw_catalog_disagreement_rejected_even_with_refreshed_hashes(tmp_path):
    cfg = static_files(tmp_path)
    specs = cfg["catalogs"]["SI"]
    path = tmp_path / specs["raw"]["path"]
    payload = json.loads(gzip.decompress(path.read_bytes()))
    block = payload["requests"][0]["payload"]["series"]
    block["data"][0][block["columns"].index("name")] = "Si-6.21"
    raw = gzip.compress(json.dumps(payload).encode())
    path.write_bytes(raw)
    specs["raw"].update(bytes=len(raw), sha256=m.digest(raw))
    path = tmp_path / specs["manifest"]["path"]
    manifest = json.loads(path.read_bytes())
    manifest["catalog_artifacts"]["series"]["raw"] = specs["raw"]
    raw = json.dumps(manifest).encode()
    path.write_bytes(raw)
    specs["manifest"].update(bytes=len(raw), sha256=m.digest(raw))
    with pytest.raises(ValueError, match="normalized catalog mismatch"):
        m.load_catalogs(tmp_path, cfg)


def test_committed_protocol_has_no_economic_activation():
    cfg = json.loads((Path(__file__).parents[1] / "configs/v91_option_contract_mapping_v1.json")
                     .read_text(encoding="utf-8-sig"))
    assert not cfg["economic_runner_enabled"] and not cfg["economic_admission"]
    assert not cfg["original_publication_proved"] and not cfg["goal_verified"]
    assert cfg["sample"]["descriptions"] == 8
