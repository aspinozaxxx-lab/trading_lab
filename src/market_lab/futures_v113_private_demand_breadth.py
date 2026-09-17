"""One dated CBR payment-breadth hypothesis, unchanged daily MIX ledger."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
from pypdf import PdfReader

from market_lab import futures_v101_manufacturing_demand as prior

base, engine, STORAGE = prior.base, prior.engine, prior.STORAGE
CONFIG = base.PROJECT / "configs/v113_private_demand_breadth_v1.json"
SEAL = base.PROJECT / "configs/v113_private_demand_breadth_v1.seal.json"
LABELS = {
    "aggregate": ("Взвешенный средний входящий поток (с весами отрасли в ВВП)",),
    "consumer": (
        "Конечное потребление д/x",
        "Конечное потребление д/х",
        "Отрасли, ориентированные на потребительский спрос",
    ),
    "investment": (
        "Валовое накопление (инвестиции)",
        "Отрасли, ориентированные на инвестиционный спрос",
    ),
    "external": ("Экспорт", "Отрасли, ориентированные на внешний спрос"),
}
MONTHS = {
    name: i
    for i, name in enumerate(
        (
            "Янв.",
            "Фев.",
            "Март",
            "Апр.",
            "Май",
            "Июнь",
            "Июль",
            "Авг.",
            "Сен.",
            "Окт.",
            "Ноя.",
            "Дек.",
        ),
        1,
    )
}
MONTHS.update({"Мар.": 3, "Июн.": 6, "Июл.": 7, "Сент.": 9})
MONTHS.update(
    {
        name: i
        for i, name in enumerate(
            (
                "Январь",
                "Февраль",
                "Март",
                "Апрель",
                "Май",
                "Июнь",
                "Июль",
                "Август",
                "Сентябрь",
                "Октябрь",
                "Ноябрь",
                "Декабрь",
            ),
            1,
        )
    }
)
MONTHS["Нояб."] = 11
MONTHS = {key.rstrip(".").lower(): value for key, value in MONTHS.items()}
MISSING = ("—", "–", "-", "н.д.")


def parse_table(text, release_date, *, numeric=False):
    """Only four first-column cells; no historical columns become earlier releases."""
    day = pd.Timestamp(release_date)
    base.require(pd.Timestamp("2021-05-01") <= day < base.BOUNDARY, "protected release date")
    text = " ".join(text.split())
    text = re.sub(r"(?<=[А-Яа-я])\-\s+(?=[а-я])", "", text)
    text = text.replace("кварт але", "квартале").replace("мес яц", "месяц")
    dates = re.findall(r"№\s*\d+\s*\(\d+\)\s*/\s*(\d{2}\.\d{2}\.\d{4})", text)
    base.require(dates == [day.strftime("%d.%m.%Y")], "PDF release header mismatch")
    base.require(
        "Таблица 1." in text and "сезонность устранена" in text and "входящих платежей" in text,
        "not the specified adjusted incoming table",
    )
    marker = "Взвешенный средний входящий поток"
    base.require(marker in text, "aggregate label absent")
    header = text[text.index("Таблица 1.") : text.index(marker)]
    month_pattern = "|".join(re.escape(m) for m in MONTHS)
    dated_month = rf"(?<![а-яё])({month_pattern})\.?\s*(20\d{{2}}|\d{{2}})(?!\d)"
    months = list(re.finditer(dated_month, header, re.I))
    base.require(bool(months), "monthly column header absent")
    base.require(
        not re.search(r"\b[IVX]+\s+кв", header[: months[0].start()]),
        "quarterly column precedes monthly column",
    )
    base.require(
        "к среднему в прошлом квартале" in header or "к среднему в предыдущем квартале" in header,
        "wrong reference period or units",
    )
    columns = header.split("Прирост к периоду")[0].split("(к среднему")[0]
    column_count = len(re.findall(dated_month, columns, re.I))
    column_count += len(re.findall(r"\b(?:[IV]+|[1-4])\s+кв\.\s+20\d{2}", columns))
    base.require(1 <= column_count <= 12, "ambiguous column count")
    year = int(months[0][2])
    observed = pd.Timestamp(
        year=year + 2000 if year < 100 else year, month=MONTHS[months[0][1].lower()], day=1
    )
    base.require(observed.to_period("M") == day.to_period("M") - 1, "not previous full month")
    source_date = observed + pd.offsets.MonthEnd(0)
    available = (
        day.tz_localize("Europe/Moscow") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    ).tz_convert("UTC")
    base.require(available < pd.Timestamp(base.BOUNDARY, tz="UTC"), "protected availability")
    values, aliases = {}, {}
    for field, choices in LABELS.items():
        positions = [
            (label, m.end())
            for label in choices
            for m in re.finditer(re.escape(label), text)
            if re.match(r"([+-]?\d+,\d|—|–|-|н\.д\.)(?=\s|$)", text[m.end() :].lstrip())
        ]
        base.require(len(positions) == 1, f"missing/ambiguous {field} label")
        label, end = positions[0]
        tail = text[end:].lstrip()
        tokens = []
        while match := re.match(r"([+-]?\d+,\d|—|–|-|н\.д\.)(?=\s|$)", tail):
            tokens.append(match[1])
            tail = tail[match.end() :].lstrip()
        base.require(len(tokens) == column_count, f"unreadable or shifted {field} cells")
        values[field] = tokens[0]
        aliases[field] = label
    result = {
        "publication_date": day,
        "observation_date": observed,
        "source_date": source_date,
        "available_at_utc": available,
        "cells_complete": all(v not in MISSING for v in values.values()),
        "data_column_count": column_count,
        "labels": aliases,
        "original_receipt_verified": False,
    }
    if numeric:
        result["values"] = values
    return result


class PdfWarnings(logging.Handler):
    def __init__(self):
        super().__init__()
        self.counts = Counter()

    def emit(self, record):
        # Count repeated xref warnings without flooding output; never discard the evidence.
        self.counts[record.getMessage().split(" object ")[0][:180]] += 1


def pdf_record(path, release, *, numeric=False):
    log = logging.getLogger("pypdf")
    previous_handlers, previous_propagate = log.handlers[:], log.propagate
    warnings = PdfWarnings()
    log.handlers, log.propagate = [warnings], False
    try:
        reader = PdfReader(path)
        candidates = []
        for i in range(min(6, len(reader.pages))):
            text = " ".join(reader.pages[i].extract_text().split())
            if "Таблица 1." in text and "Взвешенный средний входящий поток" in text:
                candidates.append((i + 1, text))
        base.require(len(candidates) == 1, "missing/ambiguous table1 page")
        page, text = candidates[0]
        meta = reader.metadata
        day = pd.Timestamp(release["release_date"])
        eod = day.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)
        clocks = {}
        for key, value in (("created", meta.creation_date), ("modified", meta.modification_date)):
            base.require(
                value is not None and value.tzinfo is not None, "missing PDF metadata clock"
            )
            stamp = pd.Timestamp(value)
            base.require(stamp < eod, "PDF metadata later than stated publication")
            clocks[key] = stamp.isoformat()
        parsed = parse_table(text, day, numeric=numeric)
        return {
            **parsed,
            "source_url": release["url"],
            "raw_sha256": release["sha256"],
            "source_file": path.name,
            "table_page": page,
            "pdf_pages": len(reader.pages),
            "pdf_clocks": clocks,
            "pdf_warnings": dict(warnings.counts),
        }
    finally:
        log.handlers, log.propagate = previous_handlers, previous_propagate


def source(cfg, storage=STORAGE, *, numeric=False):
    spec = cfg["source"]
    root = base.safe(storage, spec["root"])
    base.require(base.sha(root / "manifest.json") == spec["manifest_sha256"], "manifest drift")
    manifest = prior.read_json(root / "manifest.json")
    base.require(
        manifest["status"] == "COMPLETE_RAW_CORPUS_ONLY" and manifest["failure"] is None,
        "incomplete source corpus",
    )
    for name, digest in manifest["files"].items():
        base.require(base.sha(base.safe(root, name)) == digest, "source artifact drift")
    releases = manifest["releases"]
    months = [r["release_date"][:7] for r in releases]
    expected = [str(m) for m in pd.period_range("2021-05", "2025-12", freq="M")]
    base.require(months == expected and len(releases) == 56, "monthly release calendar")
    result = []
    for release in releases:
        stamp = release["release_date"].replace("-", "")
        name = "finflows_" + stamp + ".pdf"
        base.require(release["file"] == name, "release filename mismatch")
        path = base.safe(root, name)
        meta = prior.read_json(path.with_suffix(".pdf.metadata.json"))
        base.require(
            release["url"].startswith("https://www.cbr.ru/Collection/Collection/File/")
            and release["url"].endswith("/" + name),
            "source URL mismatch",
        )
        base.require(
            meta["url"] == release["url"]
            and meta["http_status"] == "200"
            and meta["curl_returncode"] == 0,
            "HTTP source incomplete",
        )
        base.require(
            meta["bytes"] == release["bytes"] == path.stat().st_size
            and meta["sha256"] == release["sha256"] == base.sha(path),
            "PDF drift",
        )
        mask = spec.get("unavailable_publications", {}).get(release["release_date"])
        try:
            row = pdf_record(path, release, numeric=numeric)
        except ValueError as error:
            base.require(
                mask is not None and str(error) == mask["failure"],
                f"unapproved source failure {release['release_date']}: {error}",
            )
            day = pd.Timestamp(release["release_date"])
            source_day = day.replace(day=1) - pd.Timedelta(days=1)
            row = {
                "publication_date": day,
                "observation_date": source_day.replace(day=1),
                "source_date": source_day,
                "available_at_utc": (
                    day.tz_localize("Europe/Moscow")
                    + pd.Timedelta(days=1)
                    - pd.Timedelta(nanoseconds=1)
                ).tz_convert("UTC"),
                "cells_complete": False,
                "data_column_count": None,
                "labels": {},
                "original_receipt_verified": False,
                "source_url": release["url"],
                "raw_sha256": release["sha256"],
                "source_file": name,
                "table_page": None,
                "pdf_pages": None,
                "pdf_clocks": {},
                "pdf_warnings": {},
                "admission_failure": str(error),
            }
            if numeric:
                row["values"] = dict.fromkeys(LABELS, "—")
        else:
            base.require(mask is None, "declared source failure unexpectedly disappeared")
            row["admission_failure"] = None
        result.append(row)
    return result, manifest


def states(rows):
    result = []
    for row in rows:
        values = {
            k: None if v in MISSING else Decimal(v.replace(",", "."))
            for k, v in row["values"].items()
        }
        base.require(set(values) == set(LABELS), "source value schema")
        base.require(
            all(v is None or v.is_finite() and v >= -100 for v in values.values()),
            "invalid/nonfinite growth",
        )
        ready = all(v is not None for v in values.values())
        base.require(ready == row["cells_complete"], "readiness mismatch")
        result.append(
            {
                **{
                    k: v
                    for k, v in row.items()
                    if k not in ("labels", "pdf_warnings", "pdf_clocks")
                },
                "values": json.dumps(row["values"], sort_keys=True),
                "asset_code": "MIX",
                "ready": ready,
                "primary_direction": float(
                    ready and all(values[k] > 0 for k in ("consumer", "investment", "external"))
                ),
                "control_direction": float(ready and values["aggregate"] > 0),
            }
        )
    return pd.DataFrame(result)


def targets(active, state, cfg):
    return {arm: engine.adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V113 seal drift")
    for name, digest in prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V113 file drift")
    cfg = prior.read_json(CONFIG)
    _, parent = prior.load(cfg["parent_v101_seal_sha256"])
    base.require(
        cfg["assets"] == ["MIX"]
        and cfg["protected_from"] == "2026-01-01"
        and not cfg["goal_verified"]
        and not cfg["live_trading_allowed"],
        "scope drift",
    )
    return cfg, parent


def run(cfg, parent, expected):
    rows, evidence = source(cfg)
    verified = base.preflight(parent, STORAGE)
    out = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    out.mkdir(exist_ok=False)
    base.write_json(
        out / "inputs.json",
        {
            "seal_sha256": expected,
            "source_manifest": evidence,
            "futures": verified,
            "started_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    base.write_json(out / "source_metadata.json", rows)
    numeric_rows, same_evidence = source(cfg, numeric=True)
    base.require(evidence == same_evidence, "source drift during read")
    base.require(
        rows == [{k: v for k, v in r.items() if k != "values"} for r in numeric_rows],
        "numeric/metadata source mismatch",
    )
    state = states(numeric_rows)
    state.to_parquet(out / "source_states.parquet", index=False)
    pd.testing.assert_frame_equal(state, pd.read_parquet(out / "source_states.parquet"))
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(STORAGE, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    signals = targets(active, state, cfg)
    p = signals["primary"]
    quality = {
        "ready_asset_date_fraction": float((~(p.feature_unavailable | p.stale_at_fill)).mean()),
        "source_reports": len(state),
        "ready_reports": int(state.ready.sum()),
        "long_reports": int(state.primary_direction.gt(0).sum()),
        "original_receipt_verified": False,
    }
    base.write_json(out / "source_quality.json", quality)
    base.require(
        quality["ready_asset_date_fraction"]
        >= cfg["screen_gates"]["minimum_ready_asset_date_fraction"],
        "source coverage gate",
    )
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(
        out / "case", signals, market, quality, cfg, "private_demand_breadth"
    )
    audit = prior.audit_case(out / "case", case, signals)
    base.write_json(
        out / "metrics.json",
        {
            "status": "COMPLETE",
            "protocol_id": cfg["protocol_id"],
            "seal_sha256": expected,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "case": case,
            "audit": audit,
            "limitations": cfg["limitations"],
            "goal_verified": False,
        },
    )
    base.write_json(
        out / "manifest.json",
        {
            "status": "COMPLETE",
            "seal_sha256": expected,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "files": {
                p.relative_to(out).as_posix(): base.sha(p)
                for p in sorted(out.rglob("*"))
                if p.is_file()
            },
        },
    )
    print(json.dumps({"output": str(out), "assessment": case["assessment"]}), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service user only")
    cfg, parent = load(args.seal_sha)
    run(cfg, parent, args.seal_sha)


if __name__ == "__main__":
    main()
