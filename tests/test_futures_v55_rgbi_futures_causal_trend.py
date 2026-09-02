from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from market_lab import futures_v55_rgbi_futures_causal_trend as v55


def _config() -> dict:
    return yaml.safe_load(
        (
            Path(__file__).parents[1]
            / "configs/v55_rgbi_futures_causal_trend_v1.yaml"
        ).read_text(encoding="utf-8-sig")
    )


def test_continuous_state_is_causal_and_roll_uses_new_contract_prior_overlap() -> None:
    config = _config()
    dates = pd.bdate_range("2022-01-03", periods=90)
    first_expiration = dates[72]
    series = pd.DataFrame(
        {
            "secid": ["RBA", "RBB"],
            "start_date": [dates[0], dates[0]],
            "expiration_date": [first_expiration, dates[-1] + pd.Timedelta(days=90)],
        }
    )
    rows: list[dict] = []
    for index, date in enumerate(dates):
        for security, base in (("RBA", 100.0), ("RBB", 110.0)):
            rows.append(
                {
                    "secid": security,
                    "trade_date": date,
                    "open": base * np.exp(index * 0.001),
                    "settle_price": base * np.exp(index * 0.001),
                    "volume": 100.0,
                    "num_trades": 10.0,
                }
            )
    state = v55.build_continuous_state(series, pd.DataFrame(rows), config)
    changed = state.loc[state["contract_changed"]]
    assert len(changed) == 1
    assert bool(changed.iloc[0]["roll_overlap_complete"])
    assert changed.iloc[0]["adjusted_log_return"] > 0
    assert state["target"].notna().sum() > 0
    assert state.loc[state["target"].notna(), "target"].gt(0).all()
    assert state["target"].abs().max() <= 3.0
