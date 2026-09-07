"""Install an authorized token from stdin, without argv/log/repository disclosure."""

from __future__ import annotations

import getpass
import json
import os
import re
import stat
import sys
import tempfile
import warnings
from pathlib import Path


def main() -> None:
    path = Path("/etc/trading-lab/collector.env")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise SystemExit("credential file type/owner check failed")
    warnings.simplefilter("error", getpass.GetPassWarning)
    supplied = (
        getpass.getpass("AlgoPack token (hidden): ")
        if sys.stdin.isatty()
        else sys.stdin.readline(20000)
    )
    token = supplied.strip().replace("\\_", "_")
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
        raise SystemExit("invalid credential syntax")
    old = path.read_bytes()
    lines = old.decode("utf-8").splitlines(keepends=True)
    pattern = re.compile(r"^\s*(?:export\s+)?MOEX_ALGOPACK_TOKEN\s*=")
    if sum(bool(pattern.match(line)) for line in lines) > 1:
        raise SystemExit("duplicate credential entries")
    prefix = "".join(line for line in lines if not pattern.match(line))
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    updated = (prefix + "MOEX_ALGOPACK_TOKEN=" + token + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".collector.env.algopack-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o640)
        os.fchown(descriptor, info.st_uid, info.st_gid)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != old:
            raise RuntimeError("concurrent env modification")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(json.dumps({"credential_installed": True, "mode": "0640", "value_logged": False}))


if __name__ == "__main__":
    main()
