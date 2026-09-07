"""Synthetic full-replay flow/depth sample tests; no external data or credentials."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from market_lab.futures import moex_algopack_fo_flow_depth_sample_v1 as source

SECRET = "synthetic-flow-secret"


def _row(dataset: str, secid: str = "SiZ4", *, stamp: str = "10:00:00",
         changes: dict | None = None) -> list:
    values = {"tradedate": "2024-10-15", "tradetime": stamp, "secid": secid,
              "asset_code": "SI", "SYSTIME": "2024-10-15 23:59:59",
              **{field: 1 for field in source.FIELDS[dataset]}}
    values.update(changes or {})
    return [values[field] for field in source.EXPECTED_CONFIG["columns"][dataset]]


def _page(dataset: str, rows: list[list], *, start: int = 0,
          total: int | None = None, size: int = 2) -> bytes:
    return json.dumps({
        "data": {"columns": source.EXPECTED_CONFIG["columns"][dataset], "data": rows},
        "data.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"],
                        "data": [[start, len(rows) if total is None else total, size]]},
    }).encode()


def _parents() -> list[dict]:
    return [{"dataset": dataset, **dict(zip(source.COMMON, _row(dataset, secid)[:5], strict=True))}
            for dataset in source.FIELDS for secid in source.EXPECTED_CONFIG["contracts"]]


def _responses() -> list[bytes]:
    return [_page(dataset, [_row(dataset, secid)])
            for dataset in source.FIELDS for secid in source.EXPECTED_CONFIG["contracts"]]


class FakeSession:
    def __init__(self, responses: list[bytes], status: int = 200) -> None:
        self.responses, self.status = iter(responses), status
        self.calls: list[str] = []

    def get(self, url: str, *, headers: dict, timeout: float, allow_redirects: bool) -> object:
        assert headers["Authorization"] == f"Bearer {SECRET}"
        assert timeout == 30.0 and allow_redirects is False
        self.calls.append(url)
        return SimpleNamespace(status_code=self.status, content=next(self.responses), url=url)


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    repository, storage = tmp_path / "repository", tmp_path / "storage"
    files = {}
    for relative in (source.MODULE_RELATIVE, source.transport.MODULE_RELATIVE,
                     source.inventory.MODULE_RELATIVE, "src/market_lab/__init__.py",
                     "src/market_lab/futures/__init__.py"):
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# Synthetic dependency\n")
        files[relative] = source.sha(path.read_bytes())
    path = repository / source.CONFIG_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_dump(source.EXPECTED_CONFIG).encode()
    path.write_bytes(config)
    files[source.CONFIG_RELATIVE] = source.sha(config)
    path.with_suffix(".sha256").write_text(source.sha(config), encoding="utf-8")
    seal = json.dumps({"protocol_id": source.PROTOCOL, "files": files}).encode()
    (repository / f"configs/{source.PROTOCOL}.seal.json").write_bytes(seal)
    monkeypatch.setattr(source, "PROJECT_ROOT", repository)
    monkeypatch.setattr(source, "load_parent", lambda _: _parents())
    monkeypatch.setenv(source.transport.TOKEN_ENV, SECRET)
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    return storage, source.sha(seal)


def test_frozen_contract_routes_request_only_historical_allowed_columns() -> None:
    for dataset in source.FIELDS:
        for secid in source.EXPECTED_CONFIG["contracts"]:
            parsed = urlparse(source.request_url(dataset, secid, 1000))
            query = parse_qs(parsed.query)
            assert parsed.netloc == "apim.moex.com"
            assert parsed.path.endswith(f"/{dataset}/{secid}.json")
            assert query["from"] == query["till"] == ["2024-10-15"]
            assert query["latest"] == ["0"]
            assert query["start"] == ["1000"]
            assert query["data.columns"] == [",".join(source.EXPECTED_CONFIG["columns"][dataset])]
    with pytest.raises(ValueError):
        source.request_url("tradestats", "SiZ6", 0)


@pytest.mark.parametrize("dataset,field,value", [
    ("tradestats", "trades", None), ("tradestats", "trades", 0),
    ("tradestats", "trades", 2.0), ("tradestats", "disb", -0.5),
    ("obstats", "spread_l1", -0.01), ("obstats", "spread_l10", -0.02),
    ("obstats", "levels_b", 1.5), ("obstats", "vol_b_l1", None),
])
def test_numeric_null_zero_fraction_and_signed_values_preserved(
    dataset: str, field: str, value: object,
) -> None:
    rows, _ = source.parse_page(_page(dataset, [_row(dataset, changes={field: value})]),
                                dataset, "SiZ4", 0)
    assert rows[0][field] == value
    assert type(rows[0][field]) is type(value)


@pytest.mark.parametrize("dataset,field,value", [
    ("tradestats", "trades", True), ("tradestats", "trades", "2"),
    ("tradestats", "vol", 1.5), ("tradestats", "trades_s", -1),
    ("tradestats", "val", -0.1), ("obstats", "levels_b", -1),
    ("obstats", "vol_s_l1", float("nan")), ("obstats", "spread_l1", float("inf")),
])
def test_invalid_numeric_domains_are_not_coerced(dataset: str, field: str, value: object) -> None:
    with pytest.raises(ValueError):
        source.parse_page(_page(dataset, [_row(dataset, changes={field: value})]),
                          dataset, "SiZ4", 0)


@pytest.mark.parametrize("changes", [
    {"tradedate": "2026-01-01"}, {"secid": "SiZ6"}, {"secid": None},
    {"asset_code": 42}, {"tradetime": "25:00:00"},
])
def test_date_contract_and_metadata_stay_strict(changes: dict) -> None:
    with pytest.raises(ValueError):
        source.parse_page(_page("tradestats", [_row("tradestats", changes=changes)]),
                          "tradestats", "SiZ4", 0)


def test_null_asset_metadata_preserved() -> None:
    raw = _page("tradestats", [_row("tradestats", changes={"asset_code": None})])
    rows, _ = source.parse_page(raw, "tradestats", "SiZ4", 0)
    assert rows[0]["asset_code"] is None and rows[0]["asset_code_missing"] is True


def test_full_sample_replay_and_immutable_no_secret_output(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    session = FakeSession(_responses())
    output = source.collect(storage, seal_sha, session=session)
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert len(session.calls) == 8
    assert manifest["diagnostics"]["sample_coverage_admitted"] is True
    assert manifest["historical_model_eligible"] is False
    assert all(source.audit(output, storage, seal_sha,
                            source.sha((output / "manifest.json").read_bytes())).values())
    for path in output.iterdir():
        assert SECRET.encode() not in path.read_bytes()
    for row in json.loads((output / "sample.json").read_bytes()):
        assert row["available_at"] is None and row["original_version_verified"] is False
    with pytest.raises(FileExistsError):
        source.collect(storage, seal_sha, session=FakeSession([]))


def test_mismatched_keys_and_asset_revisions_block_coverage() -> None:
    rows = []
    for dataset in source.FIELDS:
        for secid in source.EXPECTED_CONFIG["contracts"]:
            parsed, _ = source.parse_page(_page(dataset, [_row(dataset, secid)]), dataset, secid, 0)
            rows.extend(parsed)
    rows[0]["asset_code"] = "OTHER"
    rows[1]["tradetime"] = "10:05:00"
    result = source.diagnostics(rows, _parents())
    assert result["sample_coverage_admitted"] is False
    assert result["inventory_comparison"]["tradestats:SiZ4"]["asset_metadata_mismatch_keys"]
    assert result["inventory_comparison"]["tradestats:RIZ4"]["missing_keys"]
    assert result["inventory_comparison"]["tradestats:RIZ4"]["extra_keys"]


def test_obstats_only_times_are_joint_coverage_not_trade_zero_imputation() -> None:
    parents, rows = _parents(), []
    for dataset in source.FIELDS:
        for secid in source.EXPECTED_CONFIG["contracts"]:
            raw_rows = [_row(dataset, secid)]
            if dataset == "obstats":
                raw_rows.append(_row(dataset, secid, stamp="09:05:00"))
                parents.append({"dataset": dataset,
                                **dict(zip(source.COMMON, raw_rows[-1][:5], strict=True))})
            parsed, _ = source.parse_page(_page(dataset, raw_rows), dataset, secid, 0)
            rows.extend(parsed)
    result = source.diagnostics(rows, parents)
    assert result["sample_coverage_admitted"] is True
    assert result["joint_coverage"]["SiZ4"] == {"both": 1, "tradestats_only": 0, "obstats_only": 1}
    assert result["field_counts"]["tradestats:SiZ4"]["rows"] == 1


def test_field_diagnostics_are_counts_not_values() -> None:
    raw_rows = [_row("tradestats", changes={"trades": None, "vol": 0, "disb": -0.5})]
    rows, _ = source.parse_page(_page("tradestats", raw_rows), "tradestats", "SiZ4", 0)
    fields = source.diagnostics(rows, _parents())["field_counts"]["tradestats:SiZ4"]["fields"]
    assert fields["trades"] == {"null": 1, "zero": 0, "negative": 0}
    assert fields["vol"] == {"null": 0, "zero": 1, "negative": 0}
    assert fields["disb"] == {"null": 0, "zero": 0, "negative": 1}


def test_raw_tamper_fails_audit(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    output = source.collect(storage, seal_sha, session=FakeSession(_responses()))
    digest = source.sha((output / "manifest.json").read_bytes())
    (output / "raw_tradestats_SiZ4_000.json").write_bytes(b"{}")
    with pytest.raises(ValueError):
        source.audit(output, storage, seal_sha, digest)


def test_forged_normalized_value_fails_even_with_updated_hash(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    output = source.collect(storage, seal_sha, session=FakeSession(_responses()))
    sample = output / "sample.json"
    rows = json.loads(sample.read_bytes())
    rows[0]["trades"] = 999
    sample.write_bytes(json.dumps(rows).encode())
    path = output / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["sample"] = source._identity(sample)
    path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ValueError, match="audit failed"):
        source.audit(output, storage, seal_sha, source.sha(path.read_bytes()))


def test_http_failure_and_reflected_secret_have_safe_diagnostics(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    for status in (200, 403, 302):
        with pytest.raises(source.InventoryFailure) as error:
            source.collect(storage, seal_sha, session=FakeSession([SECRET.encode()], status))
        assert SECRET not in str(error.value)
        diagnostic = Path(error.value.diagnostic_path).read_bytes()
        assert SECRET.encode() not in diagnostic
    assert not list(storage.rglob("raw_*.json"))


def test_parent_is_audited_with_exact_pinned_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = source.EXPECTED_CONFIG["parent_inventory"]
    path = tmp_path / expected["path"]
    path.mkdir(parents=True)
    path.joinpath("inventory.json").write_bytes(json.dumps(_parents()).encode())
    calls = []
    monkeypatch.setattr(source.inventory, "audit", lambda *args: calls.append(args))
    assert source.load_parent(tmp_path) == _parents()
    assert calls == [(path.resolve(), expected["seal_sha256"], expected["manifest_sha256"])]


def test_invalid_seal_blocks_network(sealed: tuple[Path, str]) -> None:
    storage, _ = sealed
    session = FakeSession([])
    with pytest.raises(ValueError):
        source.collect(storage, "0" * 64, session=session)
    assert not session.calls


def test_unknown_cases_duplicate_paths_and_bad_auth_evidence_fail(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    output = source.collect(storage, seal_sha, session=FakeSession(_responses()))
    pages = json.loads((output / "manifest.json").read_bytes())["pages"]
    with pytest.raises(ValueError):
        source._replay(output, [*pages, pages[0]])
    unknown = [{**p} for p in pages]
    unknown[0]["secid"] = "OTHER"
    with pytest.raises(ValueError):
        source._replay(output, unknown)
    unauthenticated = [{**p} for p in pages]
    unauthenticated[0]["bearer_sent"] = False
    with pytest.raises(ValueError):
        source._replay(output, unauthenticated)


def test_canonical_mismatch_is_complete_but_not_coverage_admitted(
    sealed: tuple[Path, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage, seal_sha = sealed
    parents = _parents()
    parents[0]["asset_code"] = "DIFFERENT"
    parents[1]["tradetime"] = "10:05:00"
    monkeypatch.setattr(source, "load_parent", lambda _: parents)
    output = source.collect(storage, seal_sha, session=FakeSession(_responses()))
    raw = (output / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    assert manifest["status"] == "complete"
    assert manifest["diagnostics"]["sample_coverage_admitted"] is False
    changed = manifest["diagnostics"]["inventory_comparison"]["tradestats:SiZ4"]
    assert changed["asset_metadata_mismatch_keys"] == [["2024-10-15", "10:00:00"]]
    assert all(source.audit(output, storage, seal_sha, source.sha(raw)).values())


def test_complete_multi_page_sample_uses_actual_cursor(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    responses = [
        _page("tradestats", [_row("tradestats"), _row("tradestats", stamp="10:05:00")], total=3),
        _page("tradestats", [_row("tradestats", stamp="10:10:00")], start=2, total=3),
        *_responses()[1:],
    ]
    session = FakeSession(responses)
    output = source.collect(storage, seal_sha, session=session)
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert len(session.calls) == 9
    assert parse_qs(urlparse(session.calls[1]).query)["start"] == ["2"]
    assert manifest["diagnostics"]["field_counts"]["tradestats:SiZ4"]["rows"] == 3
    assert manifest["diagnostics"]["sample_coverage_admitted"] is False


def test_cross_page_duplicate_cannot_publish_canonical_sample(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    responses = [
        _page("tradestats", [_row("tradestats"), _row("tradestats", stamp="10:05:00")], total=3),
        _page("tradestats", [_row("tradestats")], start=2, total=3),
        *_responses()[1:],
    ]
    with pytest.raises(source.InventoryFailure) as error:
        source.collect(storage, seal_sha, session=FakeSession(responses))
    assert error.value.phase == "raw_replay"
    assert not list(storage.rglob("manifest.json"))


def test_changed_cursor_total_and_unfinished_page_fail(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    responses = [
        _page("tradestats", [_row("tradestats"), _row("tradestats", stamp="10:05:00")], total=3),
        _page("tradestats", [_row("tradestats", stamp="10:10:00"),
                             _row("tradestats", stamp="10:15:00")], start=2, total=4),
    ]
    with pytest.raises(source.InventoryFailure):
        source.collect(storage, seal_sha, session=FakeSession(responses))
    with pytest.raises(ValueError):
        source.parse_page(_page("tradestats", [_row("tradestats")], total=3),
                          "tradestats", "SiZ4", 0)
