"""Synthetic and structural tests for the sealed V56 RVI corridor."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from market_lab import futures_v56_rvi_outlier_short_corridor as v56


def _config() -> dict:
    payload = yaml.safe_load(v56.CONFIG_PATH.read_text(encoding="utf-8-sig"))
    payload["_config_sha256"] = v56.CONFIG_SHA256
    return payload


def _synthetic_source() -> tuple[pd.DataFrame, pd.DataFrame]:
    series = pd.DataFrame(
        {
            "secid": ["RVIH1"],
            "start_date": ["2020-12-01"],
            "expiration_date": ["2021-02-01"],
        }
    )
    dates = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08"])
    opens = [31.0, 31.0, 28.0, 22.0, 22.0]
    closes = [32.0, 29.0, 23.0, 22.0, 21.0]
    volume = [100.0] * len(dates)
    waprice = closes
    daily = pd.DataFrame(
        {
            "trade_date": dates,
            "secid": ["RVIH1"] * len(dates),
            "expiration_date": pd.to_datetime(["2021-02-01"] * len(dates)),
            "open": opens,
            "close": closes,
            "high": [33.0, 32.0, 29.0, 23.0, 22.0],
            "low": [30.0, 28.0, 22.0, 21.0, 20.0],
            "volume": volume,
            "num_trades": [10.0] * len(dates),
            "waprice": waprice,
            "value": [v * w * 100.0 for v, w in zip(volume, waprice, strict=True)],
        }
    )
    return series, daily


def test_sealed_protocol_identity_and_economics() -> None:
    config = v56._read_sealed_config()

    assert config["_config_sha256"].startswith("bc1c3f2b")
    assert config["signal"]["entry_close_gte"] == 30.0
    assert config["signal"]["take_profit_close_lte"] == 24.0
    assert config["signal"]["distant_stop_close_gte"] == 45.0
    assert config["live_trading_allowed"] is False


def test_point_value_preserves_missing_and_uses_turnover_identity() -> None:
    frame = pd.DataFrame(
        {
            "value": [6000.0, 10.0, 10.0],
            "volume": [2.0, 0.0, 1.0],
            "waprice": [30.0, 30.0, float("nan")],
        }
    )

    result = v56._point_value(frame)

    assert result.iloc[0] == 100.0
    assert pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])


def test_synthetic_take_profit_uses_next_open_and_causal_risk_cap() -> None:
    config = _config()
    config["dates"]["evaluation_end"] = "2021-01-08"
    series, daily = _synthetic_source()

    state = v56.build_front_state(series, daily, config)
    trades, counts = v56.build_trades(config, state, daily)

    assert counts["signal_sessions"] == 1
    assert counts["unresolved_entries"] == 0
    assert counts["unresolved_exits"] == 0
    assert len(trades) == 1
    trade = trades.iloc[0]
    assert trade["signal_date"] == pd.Timestamp("2021-01-04")
    assert trade["entry_date"] == pd.Timestamp("2021-01-05")
    assert trade["trigger_date"] == pd.Timestamp("2021-01-06")
    assert trade["exit_date"] == pd.Timestamp("2021-01-07")
    assert trade["exit_reason"] == "take_profit"
    assert trade["contracts"] == 7
    assert trade["gross_pnl_rub"] == 6300.0


def test_synthetic_daily_mtm_and_cost_scenarios_are_monotonic(tmp_path: Path) -> None:
    config = _config()
    config["dates"]["evaluation_end"] = "2021-01-08"
    series, daily = _synthetic_source()
    series.to_parquet(tmp_path / "series.parquet", index=False)
    daily.to_parquet(tmp_path / "daily_history.parquet", index=False)
    config["_source_root"] = tmp_path

    _, trades, ledger, metrics = v56.evaluate(config)

    assert len(trades) == 1
    assert metrics["unresolved_total"] == 0
    assert metrics["scenarios"]["primary"]["net_pnl_rub"] == 6160.0
    assert metrics["scenarios"]["doubled"]["net_pnl_rub"] == 6020.0
    assert metrics["scenarios"]["stress"]["net_pnl_rub"] == 5740.0
    final = ledger.iloc[-1]
    assert final["primary_nav"] > final["doubled_nav"] > final["stress_nav"]
    assert metrics["live_trading_allowed"] is False
