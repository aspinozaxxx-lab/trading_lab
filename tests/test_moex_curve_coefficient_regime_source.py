"""Tests for maturity-agnostic robust MOEX curve coefficient features."""

from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from market_lab.futures import moex_curve_coefficient_regime_source as regime


def _payload(rows: list[str]) -> tuple[bytes, dict[str, object]]:
    header = (
        "SESS_ID;A;B;C;D;E;S;OPTION_SERIES_ID;FUT_ISIN_ID;ISIN;"
        "SETTLEMENT_PRICE_OPEN;BEGIN\n"
    )
    stream = io.BytesIO()
    member_name = "combined.csv"
    member = (header + "".join(rows)).encode()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, member)
    content = stream.getvalue()
    protocol = {
        "parent_catalog": {
            "raw_archive_bytes": len(content),
            "raw_archive_sha256": __import__("hashlib").sha256(content).hexdigest(),
            "raw_member_name": member_name,
            "raw_member_bytes": len(member),
        }
    }
    return content, protocol


def _row(
    asset: str,
    event: str,
    series_id: int,
    value: float,
    price: str = "DO_NOT_PARSE",
) -> str:
    return (
        f"1;{value};{value};{value};{value};{value};{value};{series_id};"
        f"{series_id + 100};{asset}-9.21;{price};{event}\n"
    )


def test_parser_does_not_load_price_field(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_row("RTS", "01.09.2021 10:00", index, float(index)) for index in range(1, 3)]
    content, protocol = _payload(rows)
    monkeypatch.setattr(regime, "EXPECTED_ARCHIVE_ROWS", 2)
    monkeypatch.setattr(regime, "EXPECTED_CORE_ROWS", 2)

    frame = regime.parse_combined_archive(content, protocol)

    assert "settlement_price_open" not in frame.columns
    assert frame["a"].tolist() == [1.0, 2.0]


def test_robust_panels_preserve_asset_order_context_and_causal_deltas() -> None:
    rows: list[dict[str, object]] = []
    timezone = "Europe/Moscow"
    for day, shift in (("2021-09-01 10:00", 0.0), ("2021-09-02 10:00", 1.0)):
        event = pd.Timestamp(day, tz=timezone)
        for asset_index, asset in enumerate(regime.ASSETS):
            for series, level in enumerate((1.0, 3.0, 9.0), start=1):
                row: dict[str, object] = {
                    "event_at": event,
                    "available_at": event + pd.Timedelta(minutes=1),
                    "asset": asset,
                    "session_id": 1,
                    "option_series_id": asset_index * 100 + series,
                    "futures_isin_id": asset_index,
                    "underlying_isin": f"{asset}-9.21",
                }
                for coefficient in regime.COEFFICIENTS:
                    row[coefficient] = level + shift + asset_index
                rows.append(row)
    core = pd.DataFrame(rows)

    long = regime.build_long_panel(core)
    wide = regime.build_wide_context(long)

    first = long.loc[long["event_at"].eq(long["event_at"].min())]
    assert tuple(first["asset"]) == regime.ASSETS
    assert first.loc[first["asset"].eq("RI"), "a_median"].item() == 3.0
    assert first.loc[first["asset"].eq("RI"), "a_q25"].item() == 2.0
    assert first.loc[first["asset"].eq("RI"), "a_q75"].item() == 6.0
    assert first.loc[first["asset"].eq("RI"), "a_iqr"].item() == 4.0
    assert first.loc[first["asset"].eq("RI"), "a_mad"].item() == 2.0
    second_ri = long.loc[(long["asset"].eq("RI")) & (long["event_at"].eq(long["event_at"].max()))]
    assert second_ri["a_median_delta"].item() == 1.0
    assert len(wide) == 2
    assert np.isfinite(wide["context_br_a_median"]).all()
    assert wide["source_available_through"].eq(wide["available_at"]).all()


def test_protected_source_event_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    content, protocol = _payload([_row("RTS", "05.01.2026 10:00", 1, 1.0)])
    monkeypatch.setattr(regime, "EXPECTED_ARCHIVE_ROWS", 1)
    monkeypatch.setattr(regime, "EXPECTED_CORE_ROWS", 1)

    with pytest.raises(ValueError, match="protected"):
        regime.parse_combined_archive(content, protocol)
