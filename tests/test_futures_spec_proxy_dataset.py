"""Testy immutable spec-proxy dataset iz proverennogo futures_v5 raw."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from market_lab.futures.market_data import parse_futures_daily_payload
from market_lab.futures.spec_proxy_dataset import build_futures_spec_proxy_dataset
from market_lab.futures.specs import FuturesAssetSpec
from market_lab.io_utils import write_json

# Nachalo synthetic development period bez dostupa k holdout.
START_DATE = date(2024, 1, 1)
# Konec synthetic development period bez dostupa k holdout.
END_DATE = date(2024, 1, 5)
# Kanonicheskii ID, obshchii dlya osnovnogo i arhivnogo SECID.
CANONICAL_CONTRACT_ID = "Si:SiH4:2024-03-21"
# Polya daily ISS fixture, vklyuchaya obyazatel'nyi WAPRICE.
DAILY_COLUMNS = [
    "boardid",
    "tradedate",
    "secid",
    "open",
    "low",
    "high",
    "close",
    "value",
    "volume",
    "openposition",
    "openpositionvalue",
    "settleprice",
    "numtrades",
    "assetcode",
    "waprice",
]


def _daily_row(secid: str, trade_date: str, value: float, waprice: float) -> list[Any]:
    """Stroit validnuyu daily-stroku bez returns ili PnL."""
    return [
        "RFUD",
        trade_date,
        secid,
        waprice,
        waprice - 1.0,
        waprice + 2.0,
        waprice + 1.0,
        value,
        100.0,
        10_000.0,
        10_000.0 * (waprice + 0.5) * (value / (100.0 * waprice)),
        waprice + 0.5,
        12,
        "Si",
        waprice,
    ]


def _daily_payload(
    secid: str,
    trade_date: str,
    value: float,
    waprice: float,
    cursor_index: int,
    cursor_total: int,
    page_size: int,
) -> dict[str, Any]:
    """Upakovyvaet odnu daily-stroku s proveriaemym ISS cursor."""
    return {
        "history": {
            "columns": DAILY_COLUMNS,
            "data": [[*_daily_row(secid, trade_date, value, waprice)]],
        },
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[cursor_index, cursor_total, page_size]],
        },
    }


def _raw_archive(pages: list[dict[str, Any]]) -> bytes:
    """Sozdaet determinirovannyi gzip iz neskol'kih ISS payload-stranic."""
    payload = {
        "requests": [
            {"url": f"https://example.invalid/page/{index}", "payload": page}
            for index, page in enumerate(pages)
        ]
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return gzip.compress(serialized, mtime=0)


def _sha256(content: bytes) -> str:
    """Schitaet SHA-256 fixture-baitov dlya synthetic manifesta."""
    return hashlib.sha256(content).hexdigest()


def _write_raw_artifact(
    data_root: Path,
    stem: str,
    pages: list[dict[str, Any]],
    rows: int,
) -> tuple[dict[str, Any], Path]:
    """Pishet odin raw gzip i vozvrashchaet ego manifest-record."""
    relative = Path("raw/futures_v5/Si/segments") / stem / "daily.json.gz"
    path = data_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _raw_archive(pages)
    path.write_bytes(content)
    return (
        {
            "path": relative.as_posix(),
            "rows": rows,
            "pages": len(pages),
            "bytes": len(content),
            "sha256": _sha256(content),
        },
        path,
    )


def _write_source_fixture(data_root: Path) -> tuple[Path, tuple[Path, Path]]:
    """Sozdaet v5 manifest s dvumya storage aliases odnogo kontrakta."""
    first_pages = [
        _daily_payload("SiH4", "2024-01-02", 10_000.0, 50.0, 0, 2, 1),
        _daily_payload("SiH4", "2024-01-03", 18_000.0, 60.0, 1, 2, 1),
    ]
    second_pages = [
        _daily_payload("SiH4_2024", "2024-01-04", 28_000.0, 70.0, 0, 1, 100)
    ]
    second_pages[0]["history"]["data"][0][-1] = 0.0
    first_record, first_path = _write_raw_artifact(
        data_root,
        "primary",
        first_pages,
        rows=2,
    )
    second_record, second_path = _write_raw_artifact(
        data_root,
        "archive_alias",
        second_pages,
        rows=1,
    )
    asset = FuturesAssetSpec.from_symbol("SI")
    segments = [
        {
            "canonical_segment_id": (
                f"{CANONICAL_CONTRACT_ID}:RFUD:2024-01-01:2024-01-03"
            ),
            "canonical_contract_id": CANONICAL_CONTRACT_ID,
            "secid": "SiH4",
            "boardid": "RFUD",
            "requested_start": "2024-01-01",
            "requested_end": "2024-01-03",
            "daily": {"raw": first_record, "parquet": {}},
            "candles_10m": None,
        },
        {
            "canonical_segment_id": (
                f"{CANONICAL_CONTRACT_ID}:RFUD:2024-01-04:2024-01-05"
            ),
            "canonical_contract_id": CANONICAL_CONTRACT_ID,
            "secid": "SiH4_2024",
            "boardid": "RFUD",
            "requested_start": "2024-01-04",
            "requested_end": "2024-01-05",
            "daily": {"raw": second_record, "parquet": {}},
            "candles_10m": None,
        },
    ]
    manifest = {
        "schema_version": 1,
        "source": "official anonymous MOEX ISS",
        "asset": asdict(asset),
        "requested_start": START_DATE.isoformat(),
        "requested_end": END_DATE.isoformat(),
        "protected_from": "2026-01-01",
        "counts": {"daily_rows": 3, "board_segments": 2},
        "segment_artifacts": segments,
    }
    manifest_path = (
        data_root
        / "processed/futures_v5/Si"
        / f"manifest_{START_DATE.isoformat()}_{END_DATE.isoformat()}.json"
    )
    write_json(manifest_path, manifest)
    return manifest_path, (first_path, second_path)


def _read_manifest(path: Path) -> dict[str, Any]:
    """Chitaet BOM JSON manifesta derived ili source fixture."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def test_builds_atomic_immutable_proxy_across_storage_aliases(tmp_path: Path) -> None:
    """Dokazyvaet hashes, all-pages parsing, canonical alias map i lag-1 proxy."""
    data_root = tmp_path / "data"
    source_manifest, raw_paths = _write_source_fixture(data_root)
    source_hashes_before = {
        path: _sha256(path.read_bytes()) for path in (source_manifest, *raw_paths)
    }

    result = build_futures_spec_proxy_dataset(
        data_root,
        START_DATE,
        END_DATE,
        assets=["Si"],
    )

    assert result.rows == 3
    assert result.sessions == 3
    assert result.contracts == 1
    assert result.dataset_directory.parent == (
        data_root / "processed/futures_v5_specs_v1"
    ).resolve()
    assert not any(path.name.startswith(".") for path in result.dataset_directory.parent.iterdir())
    proxy = pd.read_parquet(result.parquet_path)
    assert proxy["contract_id"].tolist() == [CANONICAL_CONTRACT_ID] * 3
    assert proxy["asset_symbol"].tolist() == ["SI"] * 3
    assert proxy["realized_accounting_point_value"].tolist() == pytest.approx([2.0, 3.0, 4.0])
    assert proxy.loc[2, "realized_accounting_status"] == "available_fallback_after_session"
    assert proxy.loc[2, "realized_point_value_formula"] == (
        "OPENPOSITIONVALUE/(OPENPOSITION*SETTLEPRICE)"
    )
    assert pd.isna(proxy.loc[0, "sizing_point_value"])
    assert proxy.loc[1:, "sizing_point_value"].tolist() == pytest.approx([2.0, 3.0])
    assert proxy.loc[2, "sizing_observed_session_date"] == pd.Timestamp("2024-01-03")
    assert not {"return", "returns", "pnl"}.intersection(proxy.columns)

    manifest = _read_manifest(result.manifest_path)
    assert result.manifest_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert manifest["counts"] == {
        "source_manifests": 1,
        "source_raw_artifacts": 2,
        "rows": 3,
        "sessions": 3,
        "contracts": 1,
        "assets": 1,
    }
    assert manifest["quality"]["all_source_bytes_and_sha256_verified"] is True
    assert manifest["quality"]["all_daily_pages_parsed"] is True
    assert manifest["quality"]["additional_storage_alias_segments"] == 1
    assert manifest["quality"]["waprice_unusable_rows"] == 1
    assert manifest["quality"]["waprice_unusable_rows_by_asset"] == {"SI": 1}
    assert manifest["quality"]["waprice_missing_rows"] == 0
    assert manifest["quality"]["realized_primary_rows"] == 2
    assert manifest["quality"]["realized_fallback_rows"] == 1
    assert manifest["quality"]["realized_unusable_rows"] == 0
    assert manifest["quality"]["contains_pnl"] is False
    assert manifest["quality"]["contains_returns"] is False
    assert [item["pages"] for item in manifest["source_raw_daily"]] == [2, 1]
    assert all(len(item["sha256"]) == 64 for item in manifest["source_raw_daily"])
    assert len(manifest["source_manifests"][0]["sha256"]) == 64
    assert all(
        _sha256(path.read_bytes()) == digest
        for path, digest in source_hashes_before.items()
    )
    with pytest.raises(FileExistsError, match="Immutable"):
        build_futures_spec_proxy_dataset(
            data_root,
            START_DATE,
            END_DATE,
            assets=["SI"],
        )


def test_rejects_tampered_raw_before_gzip_payload_parsing(tmp_path: Path) -> None:
    """Meniaet compressed bait pri tom zhe razmere i poluchaet SHA-otkaz."""
    data_root = tmp_path / "data"
    _, raw_paths = _write_source_fixture(data_root)
    tampered = bytearray(raw_paths[0].read_bytes())
    tampered[-1] ^= 1
    raw_paths[0].write_bytes(bytes(tampered))

    with pytest.raises(ValueError, match="SHA-256"):
        build_futures_spec_proxy_dataset(
            data_root,
            START_DATE,
            END_DATE,
            assets=["SI"],
        )
    assert not (data_root / "processed/futures_v5_specs_v1").exists()


def test_rejects_raw_path_outside_data_root(tmp_path: Path) -> None:
    """Zapreshchaet traversal iz manifesta dazhe k sushchestvuyushchemu failu."""
    data_root = tmp_path / "data"
    manifest_path, _ = _write_source_fixture(data_root)
    outside = tmp_path / "outside.json.gz"
    outside.write_bytes(b"not-a-source-artifact")
    manifest = _read_manifest(manifest_path)
    manifest["segment_artifacts"][0]["daily"]["raw"]["path"] = "../outside.json.gz"
    write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="vyshel iz data root"):
        build_futures_spec_proxy_dataset(
            data_root,
            START_DATE,
            END_DATE,
            assets=["SI"],
        )


def test_blocks_future_period_before_any_filesystem_io(tmp_path: Path) -> None:
    """Peredaet nesushchestvuyushchii root i poluchaet holdout-guard pervym."""
    missing_data_root = tmp_path / "does-not-exist"
    with pytest.raises(ValueError, match="holdout"):
        build_futures_spec_proxy_dataset(
            missing_data_root,
            date(2025, 1, 1),
            date(2026, 1, 1),
            assets=["SI"],
        )
    assert not missing_data_root.exists()


def test_rejects_incomplete_cursor_even_with_matching_manifest_hash(tmp_path: Path) -> None:
    """Dokazyvaet proverku cursor posle uspeshnoi proverki raw hash/bytes."""
    data_root = tmp_path / "data"
    manifest_path, raw_paths = _write_source_fixture(data_root)
    incomplete_pages = [
        _daily_payload("SiH4", "2024-01-02", 10_000.0, 50.0, 0, 2, 1)
    ]
    incomplete = _raw_archive(incomplete_pages)
    raw_paths[0].write_bytes(incomplete)
    manifest = _read_manifest(manifest_path)
    raw_record = manifest["segment_artifacts"][0]["daily"]["raw"]
    raw_record.update(
        {
            "rows": 1,
            "pages": 1,
            "bytes": len(incomplete),
            "sha256": _sha256(incomplete),
        }
    )
    manifest["counts"]["daily_rows"] = 2
    write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="oborvan"):
        build_futures_spec_proxy_dataset(
            data_root,
            START_DATE,
            END_DATE,
            assets=["SI"],
        )


def test_parser_preserves_factual_zero_waprice_as_unusable_proxy_input() -> None:
    """Sohranyaet MOEX zero-sentinel bez imputacii, no proxy ne schitaet ego validnym."""
    payload = _daily_payload("SiH4", "2024-01-02", 10_000.0, 50.0, 0, 1, 100)
    payload["history"]["data"][0][-1] = 0.0
    frame, _ = parse_futures_daily_payload(
        payload,
        FuturesAssetSpec.from_symbol("SI"),
        expected_secid="SiH4",
    )
    assert frame.loc[0, "waprice"] == 0.0
