"""Generaciya deterministichnogo lokalnogo MOEX-podobnogo fixture."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROW_COUNT = 320  # Chislo dnevnyh barov dlya stabilnogo CPU-demo.
START_DATE = date(2023, 1, 2)  # Pervaya data sinteticheskogo fixture.


def business_days(start: date, count: int) -> list[date]:
    """Vozvrashchaet zadannoe chislo budnih kalendarnyh dnei."""
    result: list[date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def build_rows() -> list[list[object]]:
    """Stroit koleblyushchiisya OHLCV-ryad s oboimi klassami napravleniya."""
    rows: list[list[object]] = []
    previous_close = 100.0
    for offset, current_date in enumerate(business_days(START_DATE, ROW_COUNT)):
        cycle_sign = 1.0 if (offset // 8) % 2 == 0 else -1.0
        overnight = 0.0015 * cycle_sign + 0.0004 * math.sin(offset / 3.0)
        open_price = previous_close * (1.0 + overnight)
        intraday = 0.0045 * cycle_sign + 0.001 * math.sin(offset / 2.0)
        close_price = open_price * (1.0 + intraday)
        high_price = max(open_price, close_price) * 1.002
        low_price = min(open_price, close_price) * 0.998
        volume = 900_000 + (offset % 17) * 25_000
        value = volume * (open_price + close_price) / 2.0
        begin = datetime.combine(current_date, time(10, 0)).isoformat(sep=" ")
        end = datetime.combine(current_date, time(23, 49)).isoformat(sep=" ")
        rows.append(
            [
                round(open_price, 6),
                round(close_price, 6),
                round(high_price, 6),
                round(low_price, 6),
                round(value, 2),
                volume,
                begin,
                end,
            ]
        )
        previous_close = close_price
    return rows


def main() -> None:
    """Sohranyaet fixture vnutri kornya proekta s UTF-8 BOM."""
    project_root = Path(__file__).resolve().parents[1]
    target = project_root / "tests" / "fixtures" / "moex_sber_daily.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "candles": {
            "columns": ["open", "close", "high", "low", "value", "volume", "begin", "end"],
            "data": build_rows(),
        }
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )


if __name__ == "__main__":
    main()

