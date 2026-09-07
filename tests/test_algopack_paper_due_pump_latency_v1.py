"""Deterministic synthetic service delays; no wall-clock benchmark or market data."""

from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_algopack_paper_journal_v1 import NOW

from market_lab.futures import algopack_paper_due_pump_v1 as core


@pytest.mark.parametrize("is_exit", [False, True])
def test_four_assets_two_arms_do_not_age_shared_quote_between_groups(
    tmp_path, monkeypatch, is_exit
):
    clock, captures = [NOW], []
    positions = {
        f"{arm}_{asset}": dict(
            status="OPEN" if is_exit else "PENDING",
            entry={} if is_exit else None,
            intent=dict(
                asset=asset,
                secid=asset + "SYNTH",
                entry_at=NOW.isoformat(),
                exit_at=NOW.isoformat(),
            ),
        )
        for arm in ("price_flow", "price_only")
        for asset in ("BR", "MIX", "RI", "SI")
    }
    account = SimpleNamespace(
        activation=SimpleNamespace(future_start=NOW, activation_sha256="a" * 64),
        control=tmp_path / "control",
        ledger=tmp_path / "ledger",
        snapshot=lambda: dict(positions=positions),
    )

    def collect(*args, **kwargs):
        captures.append(kwargs["asset"])
        clock[0] += timedelta(seconds=2)  # Artificial response duration, not a measured SLA.
        return dict(observed_at=clock[0])

    def fill_due(*, position, quote_reference):
        age = (clock[0] - quote_reference["observed_at"]).total_seconds()
        return dict(status="FILLED" if age <= 5 else "STALE_MASK", age_seconds=age)

    runtime = SimpleNamespace(account=account, market_root=tmp_path / "market", fill_due=fill_due)
    monkeypatch.setattr(core, "ready", lambda _: None)
    monkeypatch.setattr(core.journal, "now", lambda: clock[0])
    monkeypatch.setattr(core.journal, "publish", lambda *args, **kwargs: {})
    monkeypatch.setattr(core.bridge.anchors, "transaction", lambda _: nullcontext())
    monkeypatch.setattr(core.bridge.source, "collect", collect)
    result = core.run(runtime, object(), tmp_path / "attempts", token="SYNTHETIC")
    assert captures == ["BR", "MIX", "RI", "SI"]
    assert len(result["outcomes"]) == 8
    assert [row["result"]["status"] for row in result["outcomes"]] == ["FILLED"] * 8
    assert max(row["result"]["age_seconds"] for row in result["outcomes"]) == 0
