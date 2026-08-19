"""Testy parsera besplatnogo MOEX context-nabora."""

from __future__ import annotations

from market_lab.sequence.context import parse_context_payload


def test_context_parser_accepts_null_fx_volume_and_value() -> None:
    """Proveryaet null volume/value pri strogih OHLC i UTC timestamp."""
    payload = {
        "candles": {
            "columns": [
                "open",
                "close",
                "high",
                "low",
                "value",
                "volume",
                "begin",
                "end",
            ],
            "data": [
                [12.0, 12.1, 12.2, 11.9, None, None, "2024-01-03 10:00:00", "x"]
            ],
        }
    }
    parsed = parse_context_payload(payload)
    assert parsed.index.tz is not None
    assert parsed.iloc[0]["volume"] == 0.0
    assert parsed.iloc[0]["value"] == 0.0
    assert parsed.iloc[0]["close"] == 12.1


def test_context_parser_deduplicates_and_sorts() -> None:
    """Proveryaet stabil'nuyu sortirovku i keep-last dlya dublikatov."""
    payload = {
        "candles": {
            "columns": ["begin", "open", "high", "low", "close"],
            "data": [
                ["2024-01-03 10:10:00", 10.0, 10.2, 9.9, 10.1],
                ["2024-01-03 10:00:00", 9.0, 9.2, 8.9, 9.1],
                ["2024-01-03 10:10:00", 11.0, 11.2, 10.9, 11.1],
            ],
        }
    }
    parsed = parse_context_payload(payload)
    assert parsed.index.is_monotonic_increasing
    assert len(parsed) == 2
    assert parsed.iloc[-1]["open"] == 11.0
