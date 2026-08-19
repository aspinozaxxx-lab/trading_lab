"""Atomarnaya zapis' raw i processed artefaktov korporativnyh raskrytii."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import pandas as pd

from market_lab.filings.revisions import validate_revision_chains
from market_lab.filings.schema import ReportEvent, report_event_to_mapping
from market_lab.io_utils import atomic_write_bytes, write_json

SAFE_PATH_PART = re.compile(r"[^A-Za-z0-9_.-]+")  # Fil'tr identifikatorov v imenah failov.
MEDIA_SUFFIXES = {  # Ogranichennaya karta media type v bezopasnoe rasshirenie.
    "application/json": ".json",
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/xhtml+xml": ".xhtml",
    "text/html": ".html",
    "text/plain": ".txt",
}


class AtomicFilingStore:
    """Hranit raskrytiya tol'ko v data/raw/filings i data/processed/filings pod root."""

    def __init__(self, project_root: Path) -> None:
        """Fiksiruet absolyutnyi koren' dlya vsego posledyushchego I/O."""
        self.project_root = project_root.resolve()
        self.raw_root = self.project_root / "data" / "raw" / "filings"
        self.processed_root = self.project_root / "data" / "processed" / "filings"

    def write_raw_event(self, event: ReportEvent, content: bytes) -> tuple[Path, Path]:
        """Atomarno pishet original'nye bytes i point-in-time metadata posle proverki hash."""
        digest = hashlib.sha256(content).hexdigest()
        if digest != event.artifact.content_sha256:
            raise ValueError("Syroi artefakt ne sootvetstvuet content_sha256")
        if len(content) != event.artifact.byte_size:
            raise ValueError("Syroi artefakt ne sootvetstvuet byte_size")
        issuer = _safe_part(event.issuer.symbol)
        document = _safe_part(event.document_id)
        event_id = _safe_part(event.source_event_id)
        suffix = MEDIA_SUFFIXES.get(event.artifact.media_type.lower(), ".bin")
        directory = self.raw_root / issuer / document
        raw_path = directory / f"{event_id}_{digest[:12]}{suffix}"
        metadata_path = directory / f"{event_id}_{digest[:12]}.metadata.json"
        _assert_inside(self.project_root, raw_path)
        _assert_inside(self.project_root, metadata_path)
        atomic_write_bytes(raw_path, content)
        write_json(metadata_path, report_event_to_mapping(event))
        return raw_path, metadata_path

    def write_processed_events(
        self,
        events: list[ReportEvent] | tuple[ReportEvent, ...],
        filename: str = "events.parquet",
    ) -> Path:
        """Atomarno sohranyaet deterministicheskuyu tablicu validirovannyh events."""
        unique = validate_revision_chains(events)
        rows = []
        for event in unique:
            mapping = report_event_to_mapping(event)
            rows.append(
                {
                    "issuer_symbol": event.issuer.symbol,
                    "document_id": event.document_id,
                    "source_event_id": event.source_event_id,
                    "action": event.action.value,
                    "revision_number": event.revision_number,
                    "published_at": pd.Timestamp(event.published_at).tz_convert("UTC"),
                    "artifact_sha256": event.artifact.content_sha256,
                    "event_json": json.dumps(
                        mapping,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
        frame = pd.DataFrame(rows).sort_values(
            ["published_at", "issuer_symbol", "source_event_id"],
            ignore_index=True,
        )
        return self.write_processed_frame(frame, filename)

    def write_processed_frame(self, frame: pd.DataFrame, filename: str) -> Path:
        """Atomarno pishet gotovyi causal feature/event frame v Parquet."""
        if Path(filename).name != filename or not filename.endswith(".parquet"):
            raise ValueError("Processed filename dolzhen byt' prostym imenem .parquet")
        path = self.processed_root / filename
        _assert_inside(self.project_root, path)
        _atomic_write_parquet(path, frame)
        return path


def _safe_part(value: str) -> str:
    """Prevrashchaet provider ID v odin bezopasnyi segment puti."""
    cleaned = SAFE_PATH_PART.sub("_", value.strip())
    if cleaned in {"", ".", ".."}:
        raise ValueError("Pustoi ili opasnyi identifikator puti")
    return cleaned


def _assert_inside(root: Path, path: Path) -> None:
    """Zapreshchaet vyhod storage-puti za razreshennyi koren' proekta."""
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError("Put' raskrytiya vyshel za koren' proekta")


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno zamenyaet Parquet posle polnoi zapisi vo vremennyi fail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
