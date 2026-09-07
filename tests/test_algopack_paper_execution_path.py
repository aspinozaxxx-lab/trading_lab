"""Synthetic signal/HTTP/process boundary; real source replay, pool and anchored fills."""

import json
import os
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from test_algopack_paper_execution_source_v1 import Response, calendar_data, encoded, quote_data
from test_algopack_paper_execution_source_v1 import runtime as source_fixture
from test_algopack_paper_execution_v1 import fixture
from test_algopack_paper_journal_v1 import NOW
from test_algopack_paper_preparation_worker_v1 import Process

from market_lab.futures import algopack_paper_async_due_v1 as due

pytestmark = pytest.mark.skipif(os.name != "posix", reason="actual Linux journals and locks")


def test_raw_source_to_two_arm_roundtrip_and_recovery(tmp_path, monkeypatch):
    activation, _ = source_fixture.__wrapped__(tmp_path, monkeypatch)
    bridge, worker = due.bridge, due.worker
    source = bridge.source
    for module, method in (
        (due, "ready"),
        (worker, "ready"),
        (bridge, "ready"),
        (bridge.anchors, "ready"),
        (bridge.anchors.cached, "ready"),
        (bridge.portfolio, "_ready"),
    ):
        monkeypatch.setattr(module, method, lambda _: None)
    # Activation cost is measured separately; source ready/raw checks remain real.
    monkeypatch.setattr(worker.runtime, "DATA_ROOT", tmp_path / "data")
    root = worker.runtime.DATA_ROOT / activation.activation_sha256
    root.mkdir(parents=True, mode=0o700)
    for name in ("market", "scheduler", "control", "ledger", "attempts"):
        (root / name).mkdir(mode=0o700)
    clock = [NOW, time.perf_counter()]

    def now():
        return clock[0] + timedelta(seconds=time.perf_counter() - clock[1])

    monkeypatch.setattr(due.journal, "now", now)
    consumed = fixture()["consumed"]
    monkeypatch.setattr(due.journal, "consume_forecast", lambda *_: consumed)
    children = []

    def launch(*args, **kwargs):
        child = Process()
        children.append(child)
        return child

    monkeypatch.setattr(worker.subprocess, "Popen", launch)

    class Session:
        def get(self, url, **kwargs):
            params = parse_qs(urlsplit(url).query)
            if "start" in params:
                data = calendar_data(params["start"] != ["0"])
            else:
                data = quote_data()
                stamp = now().astimezone(worker.runtime.MOSCOW)
                row = data["marketdata"]["data"][0]
                for column, value in (
                    ("SYSTIME", stamp.strftime("%Y-%m-%d %H:%M:%S")),
                    ("UPDATETIME", stamp.strftime("%H:%M:%S")),
                ):
                    row[source.BBO_COLUMNS.index(column)] = value
            return Response(url, encoded(data), 200)

    session = Session()
    bridge.anchors.initialize(root / "control", root / "ledger", activation)
    account = bridge.anchors.AnchoredPortfolio(root / "control", root / "ledger", activation)
    executor = bridge.ExecutionBridge(account, root / "market")
    samples = {}
    begin = time.perf_counter()
    quote = source.collect(
        session,
        activation=activation,
        root=root / "market",
        key="initial_quote",
        kind="quote",
        asset="BR",
        secid="BRU6",
        token="SYNTHETIC",
    )
    calendar = source.collect(
        session,
        activation=activation,
        root=root / "market",
        key="initial_calendar",
        kind="calendar",
        token="SYNTHETIC",
    )
    for arm in ("price_only", "price_flow"):
        assert (
            executor.reserve(
                asset="BR",
                arm=arm,
                forecast_reference="synthetic_signal",
                quote_reference=quote,
                calendar_reference=calendar,
            )["operation"]
            == "RESERVE"
        )
    samples["source_and_two_reservations"] = time.perf_counter() - begin
    pump = due.Executor(executor, root / "attempts")
    for field, operation in (("entry_at", "ENTRY"), ("exit_at", "EXIT")):
        row = account.snapshot()["positions"]["price_flow_BR"]
        clock[:] = [source._stamp(row["intent"][field]), time.perf_counter()]
        begin = time.perf_counter()
        pump.tick()
        assert len(pump.pool.active) == 1
        assert pump.tick()["outcomes"] == []  # A running process is not a quote.
        job = next(iter(pump.jobs.values()))
        worker.collect(session, job, activation, token="SYNTHETIC")
        children[-1].code = 0
        outcomes = pump.tick()["outcomes"]
        assert len(outcomes) == 2
        assert all(row["result"]["operation"] == operation for row in outcomes)
        assert pump.tick()["outcomes"] == []
        samples[operation] = time.perf_counter() - begin
    state = account.snapshot()
    assert state["sequence"] == 6 and not state["positions"]
    begin = time.perf_counter()
    recovered = bridge.anchors.AnchoredPortfolio(root / "control", root / "ledger", activation)
    assert recovered.snapshot() == state
    samples["anchored_reopen"] = time.perf_counter() - begin
    assert len(children) == 2 and not pump.pool.active
    print(json.dumps(dict(synthetic_only=True, seconds=samples, ledger_events=6)))
