"""Tests for independently persisted V27 forward source components."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import requests

from market_lab.futures import moex_v27_forward_component_source as source


def test_component_protocol_is_sealed_and_target_free() -> None:
    config = source.load_config()

    assert config["protocol_id"] == "futures_v27_forward_components_v1"
    assert config["live_trading_allowed"] is False
    assert config["correction_scope"]["economic_hypothesis_changed"] is False
    assert config["correction_scope"]["source_storage_atomicity_only"] is True
    assert config["causal_join"]["future_macro_snapshot_may_repair_past_decision"] is False


def test_completed_component_survives_later_provider_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_market(*args: object, **kwargs: object) -> tuple:
        del args, kwargs
        return pd.DataFrame({"source_only": [1]}), {}, ["2026-09-02"]

    monkeypatch.setattr(source, "_fetch_market", fake_market)
    monkeypatch.setattr(source, "audit", lambda path: {"synthetic": path.is_dir()})
    completed = source.collect(
        tmp_path,
        component="market_execution",
        retrieved_at="2026-09-02T11:00:00Z",
    )
    manifest = json.loads(
        (completed / "manifest.json").read_text(encoding="utf-8-sig")
    )

    assert manifest["status"] == "complete_valid"
    assert manifest["contains_return_label_target_prediction_or_pnl"] is False

    def failed_macro(*args: object, **kwargs: object) -> tuple:
        del args, kwargs
        raise requests.ConnectionError("synthetic provider outage")

    monkeypatch.setattr(source, "_fetch_macro", failed_macro)
    with pytest.raises(requests.ConnectionError, match="provider outage"):
        source.collect(
            tmp_path,
            component="macro_fred",
            retrieved_at="2026-09-02T11:01:00Z",
        )

    assert completed.is_dir()
    assert [path.name for path in tmp_path.glob("snapshot_*")] == [completed.name]
    assert not list(tmp_path.glob(".*-"))

