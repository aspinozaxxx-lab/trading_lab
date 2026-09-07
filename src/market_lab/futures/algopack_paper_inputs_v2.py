"""Pre-outcome correction: missing prior plan dates remain ineligible, not fatal.

V1 byte/time/price gates are unchanged. The actual map has four nontradable rows on
2018-01-03 with absent prior decisions. V1 failure evidence is preserved separately.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_lab.futures.algopack_paper_inputs_v1 import (
    ALIASES,
    count,
    digest,
    inspect_intraday,
    load_price_artifact,
    verified,
)

__all__ = ["inspect_intraday", "load_active_plan", "load_price_artifact"]


def load_active_plan(root: Path, record: dict) -> pd.DataFrame:
    path = verified(root, record)
    columns = [
        "effective_date",
        "decision_date",
        "observed_through",
        "asset_code",
        "contract_id",
        "secid",
        "plan_tradable",
    ]
    plan = pd.read_parquet(path, columns=columns)
    if len(plan) != count(record["rows"]) or digest(path) != record["sha256"]:
        raise ValueError("active map count or identity mismatch")
    for column in columns[:3]:
        value = pd.to_datetime(plan[column], errors="raise")
        present = value.dropna()
        if value.dt.tz is not None or not present.eq(present.dt.normalize()).all():
            raise ValueError("active map requires naive calendar dates")
        if column == "effective_date" and value.isna().any():
            raise ValueError("missing effective-date identity")
        if value.ge(pd.Timestamp("2026-01-01")).any():
            raise ValueError("active map touches protected 2026")
        plan[column] = value
    plan["asset"] = plan["asset_code"].str.upper().replace({"RTS": "RI"})
    if not plan["asset"].isin(ALIASES.values()).all():
        raise ValueError("unknown active-map asset")
    eligible = (
        plan["plan_tradable"].astype("boolean").fillna(False)
        & plan["observed_through"].notna()
        & plan["decision_date"].notna()
        & plan["observed_through"].le(plan["decision_date"])
        & plan["decision_date"].lt(plan["effective_date"])
        & plan["contract_id"].notna()
        & plan["secid"].notna()
        & plan["effective_date"].ge(pd.Timestamp("2020-01-01"))
    )
    plan["plan_eligible"] = eligible
    if plan.duplicated(["effective_date", "asset"]).any():
        raise ValueError("duplicate active-map date/asset")
    return plan.sort_values(["effective_date", "asset"], kind="stable").reset_index(drop=True)
