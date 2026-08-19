"""Bezopasnye operacii zapisi tekstovyh i binarnyh artefaktov."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

TEXT_ENCODING = "utf-8-sig"  # Edinaya kodirovka tekstovyh failov s BOM.


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Atomarno zapisivaet binarnye dannye ryadom s celevym failom."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write_text(path: Path, content: str) -> None:
    """Atomarno zapisivaet tekst v UTF-8 s BOM."""
    atomic_write_bytes(path, content.encode(TEXT_ENCODING))


def write_json(path: Path, payload: Any) -> None:
    """Sohranyaet JSON v chelovekochitaemom vide s BOM."""
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")


def write_yaml(path: Path, payload: Any) -> None:
    """Sohranyaet YAML v stabilnom chelovekochitaemom vide s BOM."""
    content = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    atomic_write_text(path, content)


def read_text(path: Path) -> str:
    """Chitaet tekstovyi fail s podderzhkoi UTF-8 BOM."""
    return path.read_text(encoding=TEXT_ENCODING)

