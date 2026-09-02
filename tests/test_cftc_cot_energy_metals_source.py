"""Synthetic-only tests for the sealed CFTC COT source collector."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import cftc_cot_energy_metals_source as source


def _row(year: int, market: str, code: str, *, report_date: str | None = None) -> dict[str, str]:
    row = {
        "Market_and_Exchange_Names": market,
        "Report_Date_as_YYYY-MM-DD": report_date or f"{year}-01-02",
        "CFTC_Contract_Market_Code": code,
        "Contract_Units": "CONTRACTS",
        "FutOnly_or_Combined": "FutOnly",
    }
    for offset, input_column in enumerate(source.INPUT_TO_OUTPUT):
        row[input_column] = str(1_000 + offset)
    row["Open_Interest_All"] = "10,000"
    return row


def _archive(year: int, *, protected: bool = False) -> bytes:
    config = source.load_config()
    markets = config["universe"]["markets"]
    report_date = "2026-01-06" if protected else None
    rows = [
        _row(year, "IRRELEVANT MARKET", "999999"),
        _row(
            year,
            "WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE",
            markets["WTI"]["cftc_contract_market_code"],
        ),
    ]
    rows.extend(
        _row(
            year,
            markets[logical]["exact_market_and_exchange_name"],
            markets[logical]["cftc_contract_market_code"],
            report_date=report_date,
        )
        for logical in ("WTI", "GOLD")
    )
    csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"f_year_{year}.txt", csv_bytes)
    return buffer.getvalue()


@dataclass
class _Response:
    content: bytes

    def raise_for_status(self) -> None:
        return None


class _Session:
    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _Response:
        del headers, timeout
        year = int(Path(url).stem.rsplit("_", maxsplit=1)[-1])
        return _Response(_archive(year))


def test_parse_selects_exact_markets_and_applies_conservative_delay() -> None:
    config = source.load_config()
    frame, record = source.parse_annual_archive(_archive(2021), 2021, config)

    assert list(frame.columns) == config["schema"]["normalized_columns"]
    assert set(frame["logical_market"]) == {"WTI", "GOLD"}
    assert record["source_rows"] == 4
    assert record["selected_rows"] == 2
    assert frame["report_date"].eq(pd.Timestamp("2021-01-02")).all()
    assert frame["available_at_utc"].eq(pd.Timestamp("2021-01-10 04:59:59+00:00")).all()


def test_parse_rejects_protected_dates() -> None:
    with pytest.raises(ValueError, match="protected report date"):
        source.parse_annual_archive(_archive(2026, protected=True), 2026, source.load_config())


def test_collect_and_audit_round_trip_from_synthetic_archives(tmp_path: Path) -> None:
    output = tmp_path / "cftc-source"

    actual = source.collect(
        output,
        session=_Session(),
        retrieved_at="2026-09-02T18:50:00Z",
    )

    assert actual == output.resolve()
    panel = pd.read_parquet(output / "cot_positions.parquet")
    assert len(panel) == 16
    assert panel.groupby("source_archive_year")["logical_market"].nunique().eq(2).all()
    audit = source.audit_bundle(output)
    assert audit["all_true"] is True
    assert all(audit["checks"].values())
