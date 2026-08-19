"""Edinaya konfiguraciya konsolnogo i failovogo logging."""

from __future__ import annotations

import logging
from pathlib import Path

from market_lab.io_utils import TEXT_ENCODING

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"  # Format zhurnala zapuska.


def configure_logging(log_path: Path, verbose: bool = False) -> None:
    """Pereustanavlivaet obrabotchiki i pishet fail v UTF-8 s BOM."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = logging.FileHandler(log_path, encoding=TEXT_ENCODING)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

