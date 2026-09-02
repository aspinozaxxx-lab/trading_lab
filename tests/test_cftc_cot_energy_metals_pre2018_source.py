"""Synthetic tests for the sealed pre-2018 CFTC source."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from market_lab.futures import cftc_cot_energy_metals_pre2018_source as source
from market_lab.futures import cftc_cot_energy_metals_source as base


def _archive(year: int) -> bytes:
    config = source.load_config()
    rows = []
    for logical in ("WTI", "GOLD"):
        market = config["universe"]["markets"][logical]
        row = {
            "Market_and_Exchange_Names": market["exact_market_and_exchange_names"][0],
            (
                "Report_Date_as_MM_DD_YYYY" if year == 2012 else "Report_Date_as_YYYY-MM-DD"
            ): "01/03/2012" if year == 2012 else f"{year}-01-03",
            "CFTC_Contract_Market_Code": market["cftc_contract_market_code"],
            "Contract_Units": "CONTRACTS",
            "FutOnly_or_Combined": "FutOnly",
        }
        for index, name in enumerate(base.INPUT_TO_OUTPUT):
            row[name] = str(1_000 + index)
        row["Open_Interest_All"] = "10,000"
        rows.append(row)
    csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode()
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


def test_protocol_is_sealed_before_pre2018_values() -> None:
    config = source.load_config()

    assert source.sha256_file(source.CONFIG_PATH) == source.CONFIG_SHA256
    assert config["frozen_later_v59_hypothesis"]["direction_rule"] == (
        "positive_short_BR_negative_long_BR_exact_zero_cash"
    )


def test_synthetic_six_year_collection_raw_replays(tmp_path: Path) -> None:
    output = source.collect(
        tmp_path / "pre2018-cftc",
        session=_Session(),
        retrieved_at="2026-09-02T19:10:00Z",
    )

    frame = pd.read_parquet(output / "cot_positions.parquet")
    assert len(frame) == 12
    assert set(frame["source_archive_year"]) == set(range(2012, 2018))
    assert source.audit_bundle(output)["all_true"] is True
