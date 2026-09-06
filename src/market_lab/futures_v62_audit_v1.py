"""Read-only, independent artifact/accounting audit of the canonical V62 run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def audit(run: Path) -> dict:
    if os.name == "nt":
        raise RuntimeError("real historical run audit is server-only")
    identity = read(run / "identity.json")
    report = read(run / "metrics.json")
    checks = {}
    for artifact in identity["artifacts"]:
        path = run / artifact["name"]
        checks[f"sha_{path.name}"] = (
            digest(path) == artifact["sha256"] and path.stat().st_size == artifact["bytes"]
        )
    candidates = pd.read_parquet(run / "candidates.parquet")
    labels = pd.read_parquet(run / "labels.parquet")
    predictions = pd.read_parquet(run / "predictions.parquet")
    cutoff = pd.Timestamp("2026-01-01", tz="UTC")
    checks["no_protected_candidates"] = bool(candidates.exit_at.lt(cutoff).all())
    checks["candidate_ids_unique"] = bool(candidates.candidate_id.is_unique)
    checks["labels_are_separate"] = not set(("raw_return", "positive", "valid")) & set(candidates)
    checks["inference_has_no_labels"] = not set(("raw_return", "positive", "valid")) & set(
        predictions
    )
    checks["label_ids_cover_all_candidates"] = set(labels.candidate_id) == set(
        candidates.candidate_id
    )
    joint = candidates.merge(labels, on="candidate_id", validate="one_to_one")
    checks["labels_available_after_exit_bar"] = bool(
        joint.available_at.eq(joint.exit_at + pd.Timedelta(minutes=10)).all()
    )
    checks["decision_precedes_target_exit"] = bool(
        candidates.decision_at.lt(candidates.exit_at).all()
    )
    checks["entry_after_completed_decision"] = bool(
        candidates.entry_at.ge(candidates.decision_at).all()
    )
    checks["all_folds_reported"] = [x["year"] for x in report["folds"]] == list(range(2021, 2026))
    eligible = candidates.loc[candidates.local_date.dt.year.between(2021, 2025)]
    for model in ("mlp", "logistic", "gap_fade", "gap_continuation"):
        arm = predictions.loc[predictions.model_id.eq(model)]
        checks[f"all_candidates_predicted_{model}"] = arm.candidate_id.is_unique and set(
            arm.candidate_id
        ) == set(eligible.candidate_id)
        desired = np.select(
            [arm.probability_long.ge(0.60), arm.probability_long.le(0.40)], [1, -1], default=0
        )
        checks[f"fixed_thresholds_{model}"] = bool(np.array_equal(desired, arm.direction))
    metrics_replay = {}
    for prefix, result in report["results"].items():
        trades = pd.read_parquet(run / f"{prefix}_trades.parquet")
        equity = pd.read_parquet(run / f"{prefix}_equity.parquet")
        orders = pd.read_parquet(run / f"{prefix}_orders.parquet")
        checks[f"bounded_requests_{prefix}"] = (
            bool(orders.filled.ge(0).all() and orders.filled.le(orders.requested).all())
            if len(orders)
            else True
        )
        checks[f"trade_counts_{prefix}"] = len(trades) == result["trade_count"]
        checks[f"participation_{prefix}"] = result["maximum_participation"] <= 0.01 + 1e-12
        checks[f"same_day_exits_{prefix}"] = (
            bool(
                trades.entry_at.dt.tz_convert("Europe/Moscow")
                .dt.date.eq(trades.exit_at.dt.tz_convert("Europe/Moscow").dt.date)
                .all()
            )
            if len(trades)
            else True
        )
        checks[f"one_trade_per_asset_session_{prefix}"] = not trades.duplicated(
            ["local_date", "asset"]
        ).any()
        if result["execution_complete"]:
            entry = (
                orders.loc[orders.kind.eq("entry")].groupby("candidate_id").filled.sum()
                if len(orders)
                else pd.Series(dtype=float)
            )
            exit_ = (
                orders.loc[orders.kind.eq("exit")].groupby("candidate_id").filled.sum()
                if len(orders)
                else pd.Series(dtype=float)
            )
            checks[f"all_filled_quantity_closed_{prefix}"] = all(
                quantity == exit_.get(candidate, 0) for candidate, quantity in entry.items()
            )
            checks[f"trade_cash_conservation_{prefix}"] = bool(
                np.isclose(
                    trades.pnl.sum(), equity.equity.iloc[-1] - 1_000_000, atol=1e-6, rtol=1e-10
                )
            )
        if len(equity):
            values = equity.equity.to_numpy(float)
            returns = values / np.r_[1_000_000.0, values[:-1]] - 1
            annual_span = (equity.local_date.iloc[-1] - equity.local_date.iloc[0]).days + 1
            cagr = (
                (values[-1] / 1_000_000) ** (365.2425 / annual_span) - 1 if values[-1] > 0 else -1
            )
            sharpe = (
                float(np.mean(returns) * math.sqrt(252) / np.std(returns))
                if np.std(returns) > 0
                else 0.0
            )
            peak, mdd = 1_000_000.0, 0.0
            for value in values:
                peak = max(peak, value)
                mdd = max(mdd, 1 - value / peak)
            replay = dict(cagr=float(cagr), sharpe=sharpe, maximum_drawdown=float(mdd))
            metrics_replay[prefix] = replay
            checks[f"independent_metric_replay_{prefix}"] = all(
                np.isclose(result[key], value, atol=1e-10, rtol=1e-10)
                for key, value in replay.items()
            )
    return dict(
        run=str(run),
        config_sha256=identity["config_sha256"],
        metrics_sha256=digest(run / "metrics.json"),
        identity_sha256=digest(run / "identity.json"),
        checks={key: bool(value) for key, value in checks.items()},
        all_passed=all(checks.values()),
        metrics_replay=metrics_replay,
        economic_verdict=report["promotion"],
        live_trading_allowed=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run)
    args.output.mkdir(parents=False, exist_ok=False)
    (args.output / "audit.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8-sig"
    )
    print(
        json.dumps(
            dict(
                all_passed=result["all_passed"],
                checks=len(result["checks"]),
                failed=[key for key, value in result["checks"].items() if not value],
                identity_sha256=result["identity_sha256"],
                metrics_sha256=result["metrics_sha256"],
            )
        )
    )


if __name__ == "__main__":
    main()
