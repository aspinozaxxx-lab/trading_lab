"""One explicit V2 after HTTP200 partial timeout; 120s transfer, no auto retries.

V1 raw/manifest remain immutable. The original collector selects the same 56 URLs
and reuses the same three samples. Its started.json pins both V1 selector script
and this replacement transport through their actual __file__ identities.
"""

import hashlib
import subprocess
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import cbr_sector_payments_corpus_20260917 as corpus
from market_lab import futures_v97_hurricane_supply as original


def fetch(url, destination, limit, seconds):
    started = time.monotonic()
    response = subprocess.run([
        "curl", "-q", "--http1.1", "-sS", "--connect-timeout", "10", "--max-time", "120",
        "--max-filesize", str(limit), "--proto", "=https", "--user-agent",
        "TradingLab private historical research", "-w", "\n__HTTP__%{http_code}", url,
    ], capture_output=True, timeout=125, check=False)
    raw, marker, status = response.stdout.rpartition(b"\n__HTTP__")
    if not marker:
        raw, status = response.stdout, b"000"
    with destination.open("xb") as handle:
        handle.write(raw)
    original.base.write_json(destination.with_suffix(".pdf.metadata.json"), {
        "url": url, "received_at_utc": datetime.now(UTC).isoformat(),
        "http_status": status.decode(), "curl_returncode": response.returncode,
        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "stderr": response.stderr.decode(errors="replace")[:500],
        "maximum_transfer_seconds": 120, "automatic_retries": 0,
    })
    time.sleep(max(0.0, seconds - (time.monotonic() - started)))
    original.base.require(response.returncode == 0 and status == b"200" and 0 < len(raw) <= limit,
                          "source HTTP failure; retained response, no automatic retry")
    return raw


if __name__ == "__main__":
    corpus.ROOT = corpus.PARENT / "corpus_v2"
    corpus.transport = SimpleNamespace(base=original.base, fetch=fetch, __file__=__file__)
    corpus.main()
