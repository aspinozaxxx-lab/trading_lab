"""One bounded CBR liquidity capture; dates/schema only, no economic outcomes."""

import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from market_lab import futures_v97_hurricane_supply as transport
from market_lab import futures_v101_manufacturing_demand as prior
from market_lab.futures import cbr_liquidity_factors_source as parser

ROOT = Path("/srv/trading_lab_data/source_evidence/cbr_bank_funding_20260917_v2/capture")
URL = (
    "https://www.cbr.ru/hd_base/bliquidity/"
    "?UniDbQuery.From=01.01.2018&UniDbQuery.Posted=True&UniDbQuery.To=31.12.2025"
)


def inventory(raw):
    parsed = parser._DataTableParser()
    parsed.feed(raw.decode("utf-8-sig"))
    tables = parsed.tables
    dated, widths = [], Counter()
    for table in tables:
        for cells in table:
            if not cells or not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", cells[0]):
                continue
            day = datetime.strptime(cells[0], "%d.%m.%Y").date().isoformat()
            prior.base.require("2018-01-01" <= day <= "2025-12-31", "source date escaped")
            dated.append(day)
            widths[len(cells)] += 1
    prior.base.require(bool(dated) and len(dated) == len(set(dated)), "no/duplicate dates")
    return {
        "table_count": len(tables),
        "dated_rows": len(dated),
        "date_min": min(dated),
        "date_max": max(dated),
        "row_width_counts": dict(widths),
        "by_year": dict(sorted(Counter(d[:4] for d in dated).items())),
        "headers": [
            cells
            for table in tables
            for cells in table
            if cells and not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", cells[0])
        ],
        "numeric_values_interpreted": False,
    }


def main():
    b = prior.base
    b.require(os.name == "posix" and os.getuid() == 999, "server service user only")
    ROOT.mkdir(exist_ok=False)
    b.write_json(
        ROOT / "started.json",
        {
            "started_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": b.sha(Path(__file__)),
            "transport_sha256": b.sha(Path(transport.__file__)),
            "table_parser_sha256": b.sha(Path(parser.__file__)),
            "prior_failure": "V1 import failed before HTTP/capture because bs4 unavailable; "
            "separate V2 reuses existing stdlib parser. No library installed or HTTP repeated.",
            "maximum_requests": 4,
            "maximum_response_bytes": 5000000,
            "no_retry_or_redirect": True,
            "economic_admission": False,
            "attribution": "Bank of Russia, banking-sector liquidity, cbr.ru",
            "scope": "Private noncommercial research, no data product, sale or raw redistribution. "
            "Source links/notices retained; no live trading admission or rights inference.",
            "limitations": "Current-vintage. Reserve-adjusted headline revises and its analytical "
            "definition changed in November2023. Publication/availability is not row date. "
            "Only dates/schema inspected; new numeric states and all market outcomes excluded.",
        },
    )
    status, failure, result = "COMPLETE_METADATA_ONLY", None, {}
    try:
        for name, url in (
            ("terms", "https://www.cbr.ru/about/"),
            ("agreement", "https://www.cbr.ru/user_agreement/"),
            ("definitions", "https://www.cbr.ru/oper_br/o_dkp/liquidity/"),
            ("liquidity", URL),
        ):
            raw = transport.fetch(url, ROOT / (name + ".html"), 5000000, 1.0)
            if name == "liquidity":
                result = inventory(raw)
    except Exception as error:
        status, failure = "FAILED_SOURCE_NO_RETRY", str(error)
    b.write_json(
        ROOT / "manifest.json",
        {
            "status": status,
            "failure": failure,
            "inventory": result,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "files": {p.name: b.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
        },
    )
    print(
        json.dumps(
            {
                "status": status,
                "failure": failure,
                "inventory": result,
                "manifest_sha256": b.sha(ROOT / "manifest.json"),
            },
            ensure_ascii=False,
        )
    )
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
