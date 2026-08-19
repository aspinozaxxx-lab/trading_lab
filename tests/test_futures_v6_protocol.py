"""Testy byte-seal, bounded paths i semantic contract futures-v6."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

import market_lab.futures.v6_protocol as protocol_module
from market_lab.futures.v6_protocol import (
    EXPECTED_FUTURES_V6_SEMANTICS,
    byte_sha256,
    load_futures_v6_protocol,
    resolve_bounded_path,
    resolve_protocol_root,
    resolve_protocol_runs,
)
from market_lab.io_utils import TEXT_ENCODING

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren s roditel'skimi seal-configs.
CONFIG_NAME = "futures_v6_experiment.yaml"  # Imya vremennogo testovogo protocola.


def _write_payload(config_path: Path, payload: dict[str, Any]) -> str:
    """Zapisivaet YAML s BOM i vozvrashchaet explicit hash tochnyh baitov."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    config_path.write_text(content, encoding=TEXT_ENCODING)
    return byte_sha256(config_path)


def _file_record(record_id: str, path: str, root: Path) -> dict[str, Any]:
    """Stroit exact record uzhe materializovannogo testovogo faila."""
    absolute = root / path
    return {
        "id": record_id,
        "path": path,
        "sha256": byte_sha256(absolute),
        "bytes": absolute.stat().st_size,
    }


def _materialize_protocol(tmp_path: Path) -> tuple[Path, dict[str, Any], str]:
    """Sozdaet malyi proekt so vsemi sealed files i dvuhstrochnymi Parquet."""
    root = tmp_path / "project"
    config_directory = root / "configs"
    config_directory.mkdir(parents=True)
    for name in ("futures_v5_protocol.yaml", "futures_v6_information_channels.yaml"):
        (config_directory / name).write_bytes((PROJECT_ROOT / "configs" / name).read_bytes())

    payload = deepcopy(EXPECTED_FUTURES_V6_SEMANTICS)
    artifact_records: list[dict[str, Any]] = []
    for identity in EXPECTED_FUTURES_V6_SEMANTICS["artifacts"]:
        record_id = str(identity["id"])
        relative_path = str(identity["path"])
        artifact_path = root / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if bool(identity["rows_required"]):
            pd.DataFrame({"value": [1, 2]}).to_parquet(artifact_path, index=False)
        else:
            artifact_path.write_bytes(f'{{"id":"{record_id}"}}\n'.encode())
        record = _file_record(record_id, relative_path, root)
        if bool(identity["rows_required"]):
            record["rows"] = 2
        artifact_records.append(record)
    payload["artifacts"] = artifact_records

    code_records: list[dict[str, Any]] = []
    for identity in EXPECTED_FUTURES_V6_SEMANTICS["code_files"]:
        record_id = str(identity["id"])
        relative_path = str(identity["path"])
        code_path = root / relative_path
        code_path.parent.mkdir(parents=True, exist_ok=True)
        code_path.write_bytes(f'# sealed test code: {record_id}\n'.encode())
        code_records.append(_file_record(record_id, relative_path, root))
    payload["code_files"] = code_records

    config_path = config_directory / CONFIG_NAME
    config_sha256 = _write_payload(config_path, payload)
    return config_path, payload, config_sha256


def test_valid_protocol_verifies_all_references_and_resolves_paths(tmp_path: Path) -> None:
    """Proveryaet load, artifact lookup i bounded root/runs helpers."""
    config_path, _, config_sha256 = _materialize_protocol(tmp_path)
    protocol = load_futures_v6_protocol(config_path, expected_sha256=config_sha256)
    expected_root = config_path.parent.parent.resolve()
    assert resolve_protocol_root(config_path, protocol) == expected_root
    assert resolve_protocol_runs(config_path, protocol) == expected_root / "runs"
    assert protocol.artifact("panel").rows == 2
    assert protocol.code_file("v6_evaluation").path.endswith("v6_evaluation.py")
    assert protocol.sources.gdelt == "disabled_429"
    assert protocol.holdout.local_read_allowed is False


def test_config_seal_rejects_one_byte_tamper(tmp_path: Path) -> None:
    """Proveryaet otkaz do YAML-parse posle odnobaitovoi podmeny config."""
    config_path, _, config_sha256 = _materialize_protocol(tmp_path)
    config_path.write_bytes(config_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="config seal mismatch"):
        load_futures_v6_protocol(
            config_path,
            expected_sha256=config_sha256,
            verify_references=False,
        )


def test_bounded_path_rejects_escape_and_absolute_path(tmp_path: Path) -> None:
    """Proveryaet fail-closed dlya traversal i absolyutnogo path."""
    root = (tmp_path / "project").resolve()
    root.mkdir()
    assert resolve_bounded_path(root, "runs/example") == root / "runs" / "example"
    with pytest.raises(ValueError, match="vyhodit za project root"):
        resolve_bounded_path(root, "../outside.parquet")
    with pytest.raises(ValueError, match="Absolute path"):
        resolve_bounded_path(root, (tmp_path / "absolute.parquet").resolve())


def test_semantic_drift_fails_even_with_fresh_matching_config_hash(tmp_path: Path) -> None:
    """Proveryaet nezavisimost' semantic seal ot byte-hasha YAML."""
    config_path, payload, _ = _materialize_protocol(tmp_path)
    payload["candidates"][1] = "hindsight_candidate"
    drifted_hash = _write_payload(config_path, payload)
    with pytest.raises(ValidationError, match="Semantic drift futures-v6"):
        load_futures_v6_protocol(
            config_path,
            expected_sha256=drifted_hash,
            verify_references=False,
        )


def test_artifact_tamper_is_detected_before_downstream_load(tmp_path: Path) -> None:
    """Proveryaet byte-size/hash artefakta posle uspeshnogo config seal."""
    config_path, payload, config_sha256 = _materialize_protocol(tmp_path)
    root = config_path.parent.parent
    panel_path = root / payload["artifacts"][0]["path"]
    panel_path.write_bytes(panel_path.read_bytes() + b"x")
    with pytest.raises(ValueError, match="Byte-size mismatch dlya panel"):
        load_futures_v6_protocol(config_path, expected_sha256=config_sha256)


def test_parent_config_seal_is_verified_as_a_reference(tmp_path: Path) -> None:
    """Proveryaet otdel'nyi byte-seal roditel'skogo v5 config."""
    config_path, _, config_sha256 = _materialize_protocol(tmp_path)
    base_path = config_path.parent / "futures_v5_protocol.yaml"
    base_path.write_bytes(base_path.read_bytes() + b"x")
    with pytest.raises(ValueError, match="base_v5_protocol"):
        load_futures_v6_protocol(config_path, expected_sha256=config_sha256)


def test_parquet_row_mismatch_is_rejected_after_byte_verification(tmp_path: Path) -> None:
    """Proveryaet exact row count bez zagruzki tablicy v pandas."""
    config_path, payload, _ = _materialize_protocol(tmp_path)
    payload["artifacts"][0]["rows"] = 3
    changed_hash = _write_payload(config_path, payload)
    with pytest.raises(ValueError, match="Parquet row mismatch dlya panel"):
        load_futures_v6_protocol(config_path, expected_sha256=changed_hash)


def test_no_parquet_metadata_is_read_before_every_byte_seal_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proveryaet dvuhfaznyi poryadok: vse hashes ran'she Parquet metadata."""
    config_path, payload, config_sha256 = _materialize_protocol(tmp_path)
    root = config_path.parent.parent
    last_code_path = root / payload["code_files"][-1]["path"]
    last_code_path.write_bytes(last_code_path.read_bytes() + b"x")
    metadata_touched = False

    def _unexpected_parquet_read(path: Path) -> None:
        """Fiksiruet narushenie poryadka proverki i nemedlenno padaet."""
        nonlocal metadata_touched
        metadata_touched = True
        raise AssertionError(f"Rannii Parquet metadata read: {path}")

    monkeypatch.setattr(protocol_module.pq, "ParquetFile", _unexpected_parquet_read)
    with pytest.raises(ValueError, match="v6_experiment"):
        load_futures_v6_protocol(config_path, expected_sha256=config_sha256)
    assert metadata_touched is False
