"""Tests for fail-closed licensed MOEX multileg report ingestion."""

from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_multileg_execution_source as subject

TRADE_DATE = date(2024, 10, 1)


def _payloads() -> dict[str, bytes]:
    dictionary = """DATE;ISIN;NUM_LEGS;ISIN_LEG;VOL
01.10.2024;SiZ4SiH5;2;SiZ4;-1
01.10.2024;SiZ4SiH5;2;SiH5;1
"""
    market_deal = """DATE;TIME;ISIN;PRICE1;PRICE;VOL;RATE;ID_DEAL;TYPE
01.10.2024;12:00:01;SiZ4SiH5;95000;-125;3;;1001;3
"""
    participant_deal = (
        "ID_DEAL;ISIN;PRICE1;PRICE;VOL;DATE;TIME;NO_BUY;NO_SELL;ID_TRADE;"
        "FEE_EX_B;FEE_CC_B\n"
        "1001;SiZ4SiH5;95000;-125;3;01.10.2024;12:00:01;2001;;9001;1.5;0.5\n"
    )
    order_log = """NUMB_ORDER;ISIN;PRICE;VOL;REST_VOL;TIP;SOST;[DATE];[TIME];TYPE
2001;SiZ4SiH5;-125;3;3;1;1;01.10.2024;11:59:59;3
2001;SiZ4SiH5;-125;3;0;1;2;01.10.2024;12:00:01;3
"""
    leg_deal = """ID_DEAL;ISIN;PRICE;VOL;DATE;TIME;ID_MULT
3001;SiZ4;95000;3;01.10.2024;12:00:01;1001
3002;SiH5;94875;3;01.10.2024;12:00:01;1001
"""
    return {
        "multileg_dict.csv": dictionary.encode(),
        "multileg_deal.csv": market_deal.encode(),
        "multilegf04XX00.csv": participant_deal.encode(),
        "multilegordlog_XX00.csv": order_log.encode(),
        "f04_XX00.csv": leg_deal.encode(),
    }


def _write_input(root: Path, *, package_name: str = "FO20241001_2.zip") -> Path:
    root.mkdir(parents=True)
    path = root / package_name
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in _payloads().items():
            archive.writestr(name, payload)
    return path


def _temporary_protocol(tmp_path: Path) -> subject.MultilegSourceProtocol:
    protocol = subject.load_protocol()
    return replace(
        protocol,
        input_directory=tmp_path / "input",
        output_directory=tmp_path / "output",
        period_start=TRADE_DATE,
        period_end=TRADE_DATE,
    )


def test_real_protocol_is_sealed_external_and_does_not_download() -> None:
    protocol = subject.load_protocol()

    assert protocol.config_sha256 == (
        "464cce7af683cea260d658dfc20d92c2b8ddf650886c7adbc366b929f2d9c462"
    )
    assert protocol.payload["source"]["network_download"] is False
    assert protocol.payload["temporal_safety"]["execution_replay_only"] is True
    assert protocol.input_directory.resolve().is_relative_to(
        Path("D:/Projects/trading_lab_data").resolve()
    )
    assert protocol.output_directory.resolve().is_relative_to(
        Path("D:/Projects/trading_lab_data").resolve()
    )


def test_closed_parsers_keep_negative_price_missing_and_exact_leg_link() -> None:
    frames = {
        subject.classify_report_name(name): subject.parse_report_bytes(
            subject.classify_report_name(name) or "",
            payload,
            TRADE_DATE,
        )
        for name, payload in _payloads().items()
    }

    market = frames["multileg_deal"]
    assert market.loc[0, "price"] == -125
    assert pd.isna(market.loc[0, "rate"])
    assert market.loc[0, "id_deal"] == "1001"
    assert frames["participant_multileg_order_log"]["sost"].tolist() == [1, 2]
    assert subject._complete_dictionary_groups(frames["multileg_dict"])
    assert subject._participant_leg_link_complete(
        frames["participant_multileg_deal"], frames["participant_leg_deal"]
    )
    assert all(
        not (set(frame.columns) & subject.SENSITIVE_COLUMNS)
        for frame in frames.values()
    )


def test_protected_package_is_rejected_before_invalid_zip_is_opened(tmp_path: Path) -> None:
    protocol = _temporary_protocol(tmp_path)
    protocol.input_directory.mkdir(parents=True)
    protected = protocol.input_directory / "FO20260102_2.zip"
    protected.write_bytes(b"this is deliberately not a zip")

    with pytest.raises(ValueError, match="protected.*before read"):
        subject.discover_input_objects(replace(protocol, period_end=date(2025, 12, 31)))


def test_synthetic_source_build_and_replay_are_exact(tmp_path: Path) -> None:
    protocol = _temporary_protocol(tmp_path)
    _write_input(protocol.input_directory)

    preflight = subject.preflight_source(protocol)
    assert all(preflight.checks.values())
    assert preflight.counts["multileg_dict_rows"] == 2
    assert preflight.counts["multileg_deal_rows"] == 1
    assert preflight.counts["participant_leg_deal_rows"] == 2

    output = subject.build_bundle(protocol)
    audit = subject.audit_bundle(protocol)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))

    assert output == protocol.output_directory.resolve()
    assert all(audit.checks.values())
    assert manifest["source_only"] is True
    assert manifest["live_trading_allowed"] is False
    assert manifest["contains_returns_targets_labels_signals_equity_or_pnl"] is False


def test_undated_file_is_rejected_without_reading_market_values(tmp_path: Path) -> None:
    protocol = _temporary_protocol(tmp_path)
    protocol.input_directory.mkdir(parents=True)
    (protocol.input_directory / "multileg_deal.csv").write_bytes(b"not read")

    with pytest.raises(ValueError, match="YYYYMMDD is required before read"):
        subject.discover_input_objects(protocol)


def test_module_contains_no_outcome_engine_or_network_client() -> None:
    text = Path(subject.__file__).read_text(encoding="utf-8-sig").lower()

    for forbidden in (
        "requests.get",
        "requests.post",
        "compute_return",
        "target_values",
        "strategy_pnl",
        "equity_curve",
    ):
        assert forbidden not in text
