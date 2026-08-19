"""Causal'naya forward-korrektirovka nepreryvnogo futures-ryada."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from market_lab.futures.roll import normalize_roll_observations

DEFAULT_ADJUSTED_PRICE_COLUMNS = (  # Cenovye kolonki dlya odinakovoi forward-popravki.
    "open",
    "high",
    "low",
    "close",
)


def _normalize_market_prices(market: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet datu i contract id, sohranyaya dopolnitel'nye cenovye polya."""
    return normalize_roll_observations(market)


def build_causal_forward_adjusted_series(
    market: pd.DataFrame,
    roll_plan: pd.DataFrame,
    price_columns: tuple[str, ...] = DEFAULT_ADJUSTED_PRICE_COLUMNS,
    method: Literal["additive", "ratio"] = "additive",
) -> pd.DataFrame:
    """Korrektiruet tol'ko tekushchii i budushchie segmenty, nikogda ne proshloe."""
    if method not in ("additive", "ratio"):
        raise ValueError("method dolzhen byt' additive ili ratio")
    required_plan = {
        "effective_date",
        "decision_date",
        "canonical_contract_id",
        "previous_contract_id",
        "action",
        "tradable",
        "overlap_old_price",
        "overlap_new_price",
    }
    if missing := required_plan - set(roll_plan.columns):
        raise ValueError(f"V roll_plan net kolonok: {sorted(missing)}")
    prices = _normalize_market_prices(market)
    available_prices = tuple(column for column in price_columns if column in prices.columns)
    if not available_prices:
        raise ValueError("Net cenovyh kolonok dlya forward-korrektirovki")
    plan = roll_plan.copy()
    plan["effective_date"] = pd.to_datetime(plan["effective_date"], errors="raise").dt.normalize()
    plan["decision_date"] = pd.to_datetime(plan["decision_date"], errors="coerce").dt.normalize()
    invalid_time = plan["decision_date"].notna() & (
        plan["decision_date"] >= plan["effective_date"]
    )
    if invalid_time.any():
        raise ValueError("Plan rola ispol'zuet ne proshloe decision_date")
    rows: list[dict[str, object]] = []
    additive_offset = 0.0
    ratio_factor = 1.0
    active_contract: str | None = None
    chain_id = 0
    pending_reset = False
    for item in plan.sort_values("effective_date").to_dict("records"):
        effective_date = item["effective_date"]
        action = str(item["action"])
        if action.startswith("carry_"):
            raise ValueError("Continuous-chain ne mozhet skryt' neispolnennuyu carry-poziciyu")
        contract_value = item["canonical_contract_id"]
        contract_id = None if pd.isna(contract_value) else str(contract_value)
        tradable = bool(item["tradable"]) and contract_id is not None
        raw_rows = prices.loc[
            (prices["trade_date"] == effective_date)
            & (prices["canonical_contract_id"] == contract_id)
        ]
        reason = str(item.get("reason", item["action"]))
        chain_break = False
        if not tradable or raw_rows.empty:
            rows.append(
                {
                    "trade_date": effective_date,
                    "canonical_contract_id": pd.NA,
                    "secid": pd.NA,
                    "tradable": False,
                    "action": "flat_skip",
                    "reason": reason if not raw_rows.empty else "missing_effective_price",
                    "chain_id": chain_id,
                    "chain_break": True,
                    "adjustment": np.nan,
                    **{column: np.nan for column in available_prices},
                }
            )
            pending_reset = True
            active_contract = None
            continue
        raw = raw_rows.iloc[0]
        if pending_reset:
            chain_id += 1
            additive_offset = 0.0
            ratio_factor = 1.0
            pending_reset = False
            chain_break = True
        elif action == "roll":
            old_anchor = item["overlap_old_price"]
            new_anchor = item["overlap_new_price"]
            valid_anchor = (
                pd.notna(old_anchor)
                and pd.notna(new_anchor)
                and np.isfinite(float(old_anchor))
                and np.isfinite(float(new_anchor))
                and (method != "ratio" or float(new_anchor) > 0.0)
            )
            if not valid_anchor:
                rows.append(
                    {
                        "trade_date": effective_date,
                        "canonical_contract_id": pd.NA,
                        "secid": pd.NA,
                        "tradable": False,
                        "action": "flat_skip",
                        "reason": "missing_roll_overlap",
                        "chain_id": chain_id,
                        "chain_break": True,
                        "adjustment": np.nan,
                        **{column: np.nan for column in available_prices},
                    }
                )
                pending_reset = True
                active_contract = None
                continue
            if method == "additive":
                additive_offset += float(old_anchor) - float(new_anchor)
            else:
                ratio_factor *= float(old_anchor) / float(new_anchor)
        elif active_contract is not None and active_contract != contract_id:
            chain_id += 1
            additive_offset = 0.0
            ratio_factor = 1.0
            chain_break = True
        adjusted = {
            column: (
                float(raw[column]) + additive_offset
                if method == "additive"
                else float(raw[column]) * ratio_factor
            )
            for column in available_prices
        }
        rows.append(
            {
                "trade_date": effective_date,
                "canonical_contract_id": contract_id,
                "secid": raw["secid"],
                "tradable": True,
                "action": action,
                "reason": reason,
                "chain_id": chain_id,
                "chain_break": chain_break,
                "adjustment": additive_offset if method == "additive" else ratio_factor,
                **adjusted,
            }
        )
        active_contract = contract_id
    return pd.DataFrame(rows).sort_values("trade_date", ignore_index=True)
