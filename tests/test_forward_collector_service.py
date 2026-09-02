"""Tests for the cross-platform systemd forward collector dispatcher."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from market_lab.ops import forward_collector as subject


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


def test_inventory_covers_every_active_windows_collector() -> None:
    actual = (
        set(subject.DIRECT_JOBS)
        | set(subject.STAGED_JOBS)
        | set(subject.PROBED_JOBS)
        | {"v27-decision", "v27-execution"}
    )
    assert actual == {
        "cross-market",
        "broad-carry",
        "cash-carry-decision",
        "cash-carry-fill",
        "lqdt-decision",
        "lqdt-fill",
        "fund-pool-decision",
        "fund-pool-fill",
        "cny-relative-value",
        "moex-rms",
        "option-surface",
        "option-surface-eod",
        "v27-decision",
        "v27-execution",
    }


def test_probe_filters_exact_identity_and_requires_one_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "marketdata": {
            "columns": ["SECID", "TRADEDATE"],
            "data": [["OTHER", "2026-09-01"], ["CNYRUBF", "2026-09-02"]],
        }
    }
    monkeypatch.setattr(subject.requests, "get", lambda *args, **kwargs: FakeResponse(payload))
    spec = {
        "url": "https://example.invalid",
        "table": "marketdata",
        "date_column": "TRADEDATE",
        "secid_column": "SECID",
        "secid": "CNYRUBF",
    }
    assert subject._probe_unique_date(spec) == "2026-09-02"


def test_staged_existing_snapshot_is_audited_and_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stage = "decision"
    source_date = datetime.now(subject.MOSCOW).strftime("%Y%m%d")
    snapshot = tmp_path / "data" / "forward" / "test-output" / f"snapshot_{source_date}_{stage}"
    snapshot.mkdir(parents=True)
    audited: list[Path] = []
    monkeypatch.setattr(subject, "_audit", lambda module, path: audited.append(path))
    monkeypatch.setattr(
        subject,
        "_run_module",
        lambda *args, **kwargs: pytest.fail("existing snapshot must not be recollected"),
    )

    subject._run_staged(("test.module", "test-output", stage), tmp_path)

    assert audited == [snapshot]


def test_matching_snapshot_audits_before_accepting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = tmp_path / "snapshot_one"
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text(
        json.dumps({"counts": {"source_dates": ["2026-09-02"]}}),
        encoding="utf-8-sig",
    )
    audited: list[tuple[str, Path]] = []
    monkeypatch.setattr(subject, "_audit", lambda module, path: audited.append((module, path)))

    result = subject._matching_snapshot(
        tmp_path, ("counts", "source_dates"), "2026-09-02", "test.module"
    )

    assert result == snapshot
    assert audited == [("test.module", snapshot)]


def test_option_surface_is_direct_and_never_deduplicated_by_source_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, ...]] = []

    def record(module: str, *arguments: str, **kwargs: object) -> str:
        calls.append((module, *arguments))
        if module == "market_lab.futures.moex_forward_option_surface_source_v2":
            snapshot = Path(arguments[1]) / f"snapshot_{len(calls)}"
            snapshot.mkdir(parents=True)
            return f"{snapshot}\n"
        return "quality\n"

    monkeypatch.setattr(subject, "_run_module", record)

    subject.run_job("option-surface", tmp_path)
    subject.run_job("option-surface", tmp_path)

    expected_output = str(
        (tmp_path / "data" / "forward" / "moex-options-surface-v2-timestamps-margin").resolve()
    )
    assert calls == [
        (
            "market_lab.futures.moex_forward_option_surface_source_v2",
            "--output-root",
            expected_output,
        ),
        (
            subject.OPTION_QUALITY_MODULE,
            "--snapshot",
            str(Path(expected_output) / "snapshot_1"),
            "--output-root",
            str(
                (
                    tmp_path
                    / "data"
                    / "forward"
                    / "moex-options-surface-v2-quality-v1"
                ).resolve()
            ),
        ),
        (
            "market_lab.futures.moex_forward_option_surface_source_v2",
            "--output-root",
            expected_output,
        ),
        (
            subject.OPTION_QUALITY_MODULE,
            "--snapshot",
            str(Path(expected_output) / "snapshot_3"),
            "--output-root",
            str(
                (
                    tmp_path
                    / "data"
                    / "forward"
                    / "moex-options-surface-v2-quality-v1"
                ).resolve()
            ),
        ),
    ]


def test_option_surface_eod_preserves_v39_v1_compatibility(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        subject,
        "_run_module",
        lambda module, *arguments, **kwargs: calls.append((module, *arguments)) or "",
    )
    subject.run_job("option-surface-eod", tmp_path)
    assert calls == [
        (
            "market_lab.futures.moex_forward_option_surface_source",
            "--output-root",
            str((tmp_path / "data" / "forward" / "moex-options-surface-v1").resolve()),
        )
    ]


def test_v27_uses_authenticated_route_only_when_key_is_valid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FRED_API_KEY", "a" * 32)
    monkeypatch.setattr(subject, "_probe_unique_date", lambda spec: "2026-09-02")
    calls: list[tuple[str, str]] = []

    def record_component(
        output: Path,
        component: str,
        source_date: str,
        match_source_date: bool,
        required: bool,
        module: str = subject.V27_MODULE,
    ) -> None:
        calls.append((component, module))

    monkeypatch.setattr(subject, "_v27_component", record_component)
    monkeypatch.setattr(subject, "_run_module", lambda *args, **kwargs: "{}")

    subject._run_v27("v27-decision", tmp_path)

    assert calls == [
        ("market_decision", subject.V27_MODULE),
        ("macro_cbr", subject.V27_MODULE),
        ("macro_fred", subject.V27_FRED_API_MODULE),
    ]


def test_systemd_units_are_hardened_and_cover_all_jobs() -> None:
    unit_root = subject.PROJECT_ROOT / "deploy" / "systemd"
    service = (unit_root / "trading-lab-collector@.service").read_text(encoding="utf-8-sig")
    timers = sorted(unit_root.glob("trading-lab-*.timer"))
    timer_text = "\n".join(path.read_text(encoding="utf-8-sig") for path in timers)
    assert len(timers) == 14
    assert "User=trading-lab" in service
    assert "ProtectSystem=strict" in service
    assert "ReadWritePaths=/srv/trading_lab_data" in service
    assert "EnvironmentFile=-/etc/trading-lab/collector.env" in service
    for job in (
        set(subject.DIRECT_JOBS)
        | set(subject.STAGED_JOBS)
        | set(subject.PROBED_JOBS)
        | {"v27-decision", "v27-execution"}
    ):
        assert f"Unit=trading-lab-collector@{job}.service" in timer_text

    option_timer = (unit_root / "trading-lab-option-surface.timer").read_text(encoding="utf-8-sig")
    assert "OnCalendar=Mon..Fri *-*-* 10..22:09/10:00" in option_timer
    assert "OnCalendar=Mon..Fri *-*-* 23:09,19,29,39,55:00" in option_timer
    assert "Persistent=false" in option_timer
    option_eod_timer = (unit_root / "trading-lab-option-surface-eod.timer").read_text(
        encoding="utf-8-sig"
    )
    assert "OnCalendar=Mon..Fri *-*-* 23:57:00" in option_eod_timer
    assert "Unit=trading-lab-collector@option-surface-eod.service" in option_eod_timer
