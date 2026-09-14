"""Fixed qualitative CBR next-action guidance versus the announced action."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from market_lab import futures_v68_reported_option_flow as shared
from market_lab.futures import cbr_policy_releases_source_v2 as source

base = shared.base
ARMS = shared.ARMS
CONFIG = base.PROJECT / "configs/v72_cbr_policy_guidance_v1.json"
SEAL = base.PROJECT / "configs/v72_cbr_policy_guidance_v1.seal.json"
FUTURE = re.compile(
    r"\b(?:допускает|будет оценивать|будет рассматривать|видит пространство|сохраняет пространство|"
    r"может потребоваться|готов|не исключает|возможност[ьи]|возможно|потребуется)\b"
)
NEGATIVE = re.compile(
    r"не планирует|не видит (?:необходимости|оснований)|не ожидает|нет необходимости|"
    r"не потребуется|не рассматривает|не допускает|не будет"
)
ACTUAL = re.compile(r"принял[аи]? решение|принято решение")
RATE = r"\s+(?:(?:уровня|величины)\s+)?ключев[а-я]*\s+ставк[а-я]*"
HIKE = re.compile(r"(?:повышени[а-я]*|повысить|повысит[а-я]*|повышать|увеличени[а-я]*)" + RATE)
CUT = re.compile(r"(?:снижени[а-я]*|снизить|снизит[а-я]*|снижать|уменьшени[а-я]*)" + RATE)


def classify(headline, paragraphs):
    title = " ".join(str(headline).lower().replace("ё", "е").split())
    up = bool(re.search(r"\bповыс[а-я]*|\bповыш[а-я]*", title))
    down = bool(re.search(r"\bсниз[а-я]*|\bснижен[а-я]*", title))
    hold = bool(re.search(r"\bсохран[а-я]*", title))
    headline_known = sum((up, down, hold)) == 1
    action = (1 if up else (-1 if down else 0)) if headline_known else np.nan
    evidence, directions, ignored = [], set(), []
    for paragraph in paragraphs:
        for original in re.split(r"(?<=[.!?;])\s+", str(paragraph)):
            sentence = " ".join(original.lower().replace("ё", "е").split())
            if not FUTURE.search(sentence) or ACTUAL.search(sentence):
                continue
            signs = {sign for sign, pattern in ((1, HIKE), (-1, CUT)) if pattern.search(sentence)}
            if not signs:
                continue
            if NEGATIVE.search(sentence):
                ignored.append(original)
                continue
            evidence.append(original)
            directions.update(signs)
    reason = (
        "ambiguous_both_directions"
        if len(directions) > 1
        else (
            "explicit_hike"
            if directions == {1}
            else ("explicit_cut" if directions == {-1} else "no_explicit_direction")
        )
    )
    ready = headline_known and any(str(p).strip() for p in paragraphs)
    guidance = next(iter(directions)) if len(directions) == 1 else 0
    return {
        "ready": ready,
        "reason": reason if ready else "unknown_headline_or_empty_body",
        "headline_action": action,
        "guidance_action": guidance,
        "primary_direction": float(-guidance) if ready else np.nan,
        "control_direction": float(-action) if ready else np.nan,
        "matched_sentences_json": json.dumps(evidence, ensure_ascii=False),
        "negated_sentences_json": json.dumps(ignored, ensure_ascii=False),
    }


def states(raw, cfg):
    d = raw.copy()
    d["publication_date"] = pd.to_datetime(d.publication_date)
    d["available_at_utc"] = pd.to_datetime(d.available_at_utc, utc=True)
    base.require(
        d.publication_date.notna().all()
        and d.publication_date.between(cfg["period"]["start"], cfg["period"]["end"]).all()
        and d.publication_date.lt(base.BOUNDARY).all(),
        "protected release",
    )
    base.require(not d.source_url.duplicated().any(), "duplicate release")
    base.require(not d.publication_date.duplicated().any(), "ambiguous same-day releases")
    earliest = (
        d.publication_date.dt.tz_localize("Europe/Moscow")
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).dt.tz_convert("UTC")
    base.require(
        d.available_at_utc.notna().all() and d.available_at_utc.ge(earliest).all(),
        "premature source clock",
    )
    base.require(d.available_at_utc.lt("2026-01-01T00:00:00Z").all(), "protected availability")
    rows = []
    for event in d.itertuples(index=False):
        facts = classify(event.headline, event.paragraphs)
        for asset in cfg["assets"]:
            rows.append(
                {
                    "asset_code": asset,
                    "source_date": event.publication_date,
                    "available_at_utc": event.available_at_utc,
                    "headline": event.headline,
                    "source_url": event.source_url,
                    "raw_sha256": event.raw_sha256,
                    **facts,
                }
            )
    base.require(bool(rows), "no source releases")
    return pd.DataFrame(rows).sort_values(["asset_code", "source_date"], ignore_index=True)


def targets(active, state, arm, cfg):
    """Same-date completed release is eligible at EOD; never same-date execution."""
    base.require(arm in ARMS, "unknown arm")
    parts = []
    for asset in cfg["assets"]:
        left = active.loc[active.asset_code.eq(asset), base.ACTIVE_COLS].copy()
        for column in ("decision_date", "effective_date", "observed_through"):
            left[column] = pd.to_datetime(left[column])
        left = left.loc[
            left.decision_date.notna()
            & left.effective_date.between(cfg["period"]["start"], cfg["period"]["end"])
        ].sort_values("decision_date")
        base.require(not left.empty, "missing map")
        base.require(left.decision_date.lt(left.effective_date).all(), "noncausal map")
        base.require(left.observed_through.le(left.decision_date).all(), "future map")
        base.require(left.effective_date.lt(base.BOUNDARY).all(), "protected map")
        base.require(not left.effective_date.duplicated().any(), "duplicate map")
        left["decision_at_utc"] = (
            left.decision_date.dt.tz_localize("Europe/Moscow")
            + pd.Timedelta(days=1)
            - pd.Timedelta(nanoseconds=1)
        ).dt.tz_convert("UTC")
        right = state.loc[state.asset_code.eq(asset)].drop(columns="asset_code")
        frame = pd.merge_asof(
            left,
            right.sort_values(["available_at_utc", "source_date"]),
            left_on="decision_at_utc",
            right_on="available_at_utc",
            direction="backward",
            allow_exact_matches=True,
        )
        complete = frame.source_date.le(frame.decision_date)
        fresh = (frame.effective_date - frame.source_date).dt.days.le(
            cfg["signal"]["maximum_source_age_at_fill_calendar_days"]
        )
        delay = (frame.effective_date - frame.decision_date).dt.days.le(
            cfg["signal"]["maximum_decision_to_fill_calendar_days"]
        )
        frame["feature_unavailable"] = ~(frame.ready.astype("boolean").fillna(False) & complete)
        frame["stale_at_fill"] = ~(fresh & delay)
        frame["source_unavailable"] = ~(
            frame.plan_tradable.fillna(False).astype(bool) & frame.contract_id.notna()
        )
        frame["requested_weight"] = frame[f"{arm}_direction"] * cfg["execution"]["weight_per_asset"]
        admitted = ~(frame.feature_unavailable | frame.stale_at_fill | frame.source_unavailable)
        frame["target_weight"] = frame.requested_weight.where(admitted, 0.0)
        frame["terminal_flat"] = False
        frame = frame.sort_values("effective_date", ignore_index=True)
        frame.loc[frame.index[-1], ["target_weight", "terminal_flat"]] = [0.0, True]
        frame.loc[frame.target_weight.eq(0), "contract_id"] = None
        frame["provenance"] = cfg["protocol_id"] + "_" + arm
        parts.append(frame)
    out = pd.concat(parts, ignore_index=True).sort_values(["effective_date", "asset_code"])
    base.require(out.target_weight.notna().all(), "unknown target")
    base.require(
        out.groupby("effective_date").asset_code.nunique().eq(len(cfg["assets"])).all(),
        "incomplete joint target",
    )
    gross = out.groupby("effective_date").target_weight.apply(lambda x: x.abs().sum())
    base.require(gross.le(cfg["execution"]["maximum_signal_gross"] + 1e-12).all(), "gross breach")
    return out.reset_index(drop=True)


def load(expected):
    base.require(base.sha(SEAL) == expected, "V72 seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V72 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    source.load(cfg["source"]["seal_sha256"])
    base.require(cfg["protected_from"] == "2026-01-01", "boundary drift")
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    base.require(cfg["assets"] == ["MIX", "SI"], "universe drift")
    base.require(cfg["execution"]["initial_cash_rub"] == base.CAPITAL, "capital drift")
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def preflight(cfg, parent, storage):
    spec = cfg["source"]
    root = base.safe(storage, spec["root"])
    base.require(base.sha(root / "manifest.json") == spec["manifest_sha256"], "manifest drift")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    base.require(manifest["processed"] == spec["processed"], "source declaration drift")
    base.require(manifest["seal_sha256"] == spec["seal_sha256"], "source seal drift")
    path = base.safe(root, spec["processed"]["path"])
    base.require(base.sha(path) == spec["processed"]["sha256"], "source bytes drift")
    base.require(path.stat().st_size == spec["processed"]["bytes"], "source size drift")
    pf = pq.ParquetFile(path)
    base.require(pf.metadata.num_rows == spec["processed"]["rows"], "source row drift")
    base.require(set(spec["allowed_columns"]) <= set(pf.schema_arrow.names), "source schema")
    dates = pd.to_datetime(pd.read_parquet(path, columns=["publication_date"]).publication_date)
    base.require(
        dates.notna().all()
        and dates.lt(base.BOUNDARY).all()
        and dates.between(cfg["period"]["start"], cfg["period"]["end"]).all(),
        "protected source",
    )
    return {"source": spec, "futures": base.preflight(parent, storage), "all_true": True}


def assess(metrics, quality, cfg):
    result = shared.assess(metrics, quality, cfg)
    for cost, value in metrics["primary"].items():
        result["checks"][cost + "_meaningful_excess"] = (
            value["cagr"] - metrics["control"][cost]["cagr"]
            >= cfg["screen_gates"]["minimum_cagr_excess_over_control_each_cost"]
        )
    if result["verdict"] == "STAGE2_CANDIDATE" and not all(result["checks"].values()):
        result["verdict"] = "REJECT_STAGE1"
    return result


def run(cfg, parent, storage, expected):
    base.require(
        os.name == "posix" and str(storage.resolve()) == "/srv/trading_lab_data", "server only"
    )
    verified = preflight(cfg, parent, storage)
    output = base.safe(storage, f"runs/{cfg['protocol_id']}_{expected[:12]}")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    base.write_json(output / "inputs.json", verified)
    spec = cfg["source"]
    raw = pd.read_parquet(
        base.safe(storage, spec["root"]) / spec["processed"]["path"],
        columns=spec["allowed_columns"],
    )
    state = states(raw, cfg)
    state.to_parquet(output / "policy_states.parquet", index=False)
    events = state.drop_duplicates("source_url")
    quality = {
        "source_releases": len(raw),
        "ready_releases": int(events.ready.sum()),
        "ready_asset_date_fraction": float(events.ready.mean()),
        "reason_counts": {str(k): int(v) for k, v in events.reason.value_counts().items()},
        "headline_action_counts": {
            str(k): int(v) for k, v in events.headline_action.value_counts(dropna=False).items()
        },
        "original_vintages_proved": False,
    }
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(storage, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    obs = pd.read_parquet(
        base.safe(storage, declared["observations"]["path"]), columns=base.OBS_COLS
    )
    specs = pd.read_parquet(
        base.safe(storage, declared["specs"]["path"]), columns=sorted(base.SPEC_PROXY_COLUMNS)
    )
    # The exact observation/spec join is built BEFORE applying the common asset/date mask.
    market = base.build_portfolio_market(
        obs.rename(
            columns={
                "trade_date": "session_date",
                "logical_asset": "asset_code",
                "canonical_contract_id": "contract_id",
            }
        ),
        specs,
    )
    market = market.loc[
        market.asset_code.isin(cfg["assets"])
        & pd.to_datetime(market.session_date).between(cfg["period"]["start"], cfg["period"]["end"])
    ]
    metrics, counts = {}, {}
    for arm in ARMS:
        signal = targets(active, state, arm, cfg)
        signal.to_parquet(output / f"targets_{arm}.parquet", index=False)
        counts[arm] = {
            "decisions": len(signal),
            "decision_dates": int(signal.decision_date.nunique()),
            "nonzero_targets": int(signal.target_weight.ne(0).sum()),
            "used_releases": int(signal.loc[signal.target_weight.ne(0), "source_url"].nunique()),
            "feature_unavailable": int(signal.feature_unavailable.sum()),
            "source_unavailable": int(signal.source_unavailable.sum()),
            "stale_at_fill": int(signal.stale_at_fill.sum()),
        }
        metrics[arm] = {}
        for cost, (ticks, fee) in cfg["execution"]["costs"].items():
            result = base.run_futures_portfolio_ledger(
                market.loc[pd.to_datetime(market.session_date).le(signal.effective_date.max())],
                signal,
                base.FuturesPortfolioLedgerConfig(
                    initial_cash=base.CAPITAL,
                    expected_assets=tuple(cfg["assets"]),
                    maximum_gross_notional_multiple=cfg["execution"]["maximum_gross_multiple"],
                    initial_margin_buffer_multiplier=cfg["execution"]["margin_buffer"],
                    maximum_participation=cfg["execution"]["maximum_participation"],
                    slippage_ticks=ticks,
                    fee_multiplier=fee,
                    execution_atomicity="asset",
                    unexecutable_target_policy="cancel_and_clip",
                ),
            )
            metrics[arm][cost] = shared.summarize(result)
            for kind in ("ledger", "orders", "positions"):
                getattr(result, kind).to_parquet(
                    output / f"{kind}_{arm}_{cost}.parquet", index=False
                )
            print(json.dumps({"completed": arm, "costs": cost}), flush=True)
    payload = {
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": expected,
        "stage": 1,
        "metrics": metrics,
        "counts": counts,
        "source_quality": quality,
        "assessment": assess(metrics, quality, cfg),
        "economic_runtime_seconds": time.monotonic() - started,
        "limitations": cfg["limitations"],
        "goal_verified": False,
    }
    base.write_json(output / "metrics.json", payload)
    base.write_json(
        output / "identity.json",
        {
            "seal_sha256": expected,
            "files": {p.name: base.sha(p) for p in sorted(output.iterdir()) if p.is_file()},
        },
    )
    print(json.dumps({"output": str(output), "assessment": payload["assessment"]}), flush=True)


def audit(output, cfg, parent, storage, expected):
    preflight(cfg, parent, storage)
    identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
    base.require(identity["seal_sha256"] == expected, "run identity drift")
    for name, digest in identity["files"].items():
        base.require(base.sha(base.safe(output, name)) == digest, "artifact drift")
    payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    base.require(
        payload["seal_sha256"] == expected and payload["protocol_id"] == cfg["protocol_id"],
        "run drift",
    )
    spec = cfg["source"]
    raw = pd.read_parquet(
        base.safe(storage, spec["root"]) / spec["processed"]["path"],
        columns=spec["allowed_columns"],
    )
    replay_state = states(raw, cfg)
    pd.testing.assert_frame_equal(replay_state, pd.read_parquet(output / "policy_states.parquet"))
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(storage, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    replays = 0
    for arm, costs in payload["metrics"].items():
        signal = pd.read_parquet(output / f"targets_{arm}.parquet")
        pd.testing.assert_frame_equal(targets(active, replay_state, arm, cfg), signal)
        used = signal.loc[signal.target_weight.ne(0)]
        base.require(used.available_at_utc.le(used.decision_at_utc).all(), "future source")
        base.require(used.source_date.le(used.decision_date).all(), "unfinished release")
        base.require(used.decision_date.lt(used.effective_date).all(), "same-day fill")
        for cost, value in costs.items():
            ledger = pd.read_parquet(output / f"ledger_{arm}_{cost}.parquet")
            replay = base._performance_metrics(
                ledger.ending_cash, ledger.session_date, base.CAPITAL
            )
            base.require(all(np.isclose(value[k], v) for k, v in replay.items()), "metric drift")
            days = pd.to_datetime(ledger.session_date)
            daily = ledger.ending_cash / ledger.starting_cash - 1
            annual = {
                str(year): float(np.prod(1 + daily.loc[days.dt.year.eq(year)]) - 1)
                for year in sorted(days.dt.year.unique())
            }
            base.require(set(annual) == set(value["annual_returns"]), "annual calendar drift")
            base.require(
                all(np.isclose(value["annual_returns"][k], v) for k, v in annual.items()),
                "annual metric drift",
            )
            base.require(
                value["positive_years"] == sum(v > 0 for v in annual.values()),
                "positive-year drift",
            )
            base.require(np.isclose(value["worst_year"], min(annual.values())), "worst-year drift")
            positions = pd.read_parquet(output / f"positions_{arm}_{cost}.parquet")
            base.require(
                all(value[k] == v for k, v in shared.position_counts(positions).items()),
                "count drift",
            )
            orders = pd.read_parquet(output / f"orders_{arm}_{cost}.parquet")
            filled = orders.loc[orders.filled]
            paid = filled.commission_cost.sum() + filled.slippage_cost.sum()
            base.require(np.isclose(paid, value["total_cost"]), "cost drift")
            base.require(
                np.isclose(ledger.variation_margin.sum() - paid, value["net_pnl"]), "cash drift"
            )
            replays += 1
    base.require(replays == 4, "incomplete screen")
    base.require(
        assess(payload["metrics"], payload["source_quality"], cfg) == payload["assessment"],
        "verdict drift",
    )
    return {
        "artifact_hashes": len(identity["files"]),
        "state_target_replay": True,
        "metric_count_cash_replays": replays,
        "all_true": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    cfg, parent = load(args.seal_sha)
    if args.audit:
        print(json.dumps(audit(args.audit, cfg, parent, args.storage_root, args.seal_sha)))
    else:
        run(cfg, parent, args.storage_root, args.seal_sha)


if __name__ == "__main__":
    main()
