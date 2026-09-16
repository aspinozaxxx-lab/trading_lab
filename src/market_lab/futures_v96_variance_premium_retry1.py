"""Source-only HTTP/1.1 correction; all V96 economics remain byte-identical."""

from __future__ import annotations

import io
import json
import subprocess
import urllib.request
import urllib.response

from market_lab import futures_v96_variance_premium as original

CONFIG = original.base.PROJECT / "configs/v96_variance_premium_retry1.json"
SEAL = original.base.PROJECT / "configs/v96_variance_premium_retry1.seal.json"
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500&cosd=2018-01-01&coed=2025-12-31"
USER_AGENT = (
    "Mozilla/5.0 (compatible; MarketLabResearch/1.0; "
    "+https://github.com/aspinozaxxx-lab/trading_lab)"
)


class CurlSource(original.NoRedirect, urllib.request.HTTPSHandler):
    """Use the successful anonymous HEAD transport, without cookies or redirects."""

    def https_open(self, req):
        original.base.require(req.full_url == URL and req.get_method() == "GET", "source URL")
        completed = subprocess.run(
            [
                "curl",
                "--http1.1",
                "--proto",
                "=https",
                "--silent",
                "--show-error",
                "--max-time",
                "45",
                "--max-filesize",
                "2000000",
                "--user-agent",
                USER_AGENT,
                "--header",
                "Accept: text/csv",
                "--header",
                "Accept-Encoding: identity",
                "--header",
                "Connection: close",
                "--write-out",
                "\n%{http_code}",
                URL,
            ],
            capture_output=True,
            check=False,
            timeout=50,
        )
        original.base.require(completed.returncode == 0, "bounded curl source failed")
        body, code = completed.stdout.rsplit(b"\n", 1)
        original.base.require(
            code == b"200" and 0 < len(body) <= 2_000_000, "HTTP status or size; redirect forbidden"
        )
        response = urllib.response.addinfourl(
            io.BytesIO(body), {"Content-Type": "application/csv"}, URL, code=200
        )
        response.msg = "OK"
        return response


def check_unchanged_economics():
    before = json.loads(original.CONFIG.read_text(encoding="utf-8"))
    after = json.loads(CONFIG.read_text(encoding="utf-8"))
    for key in ("protocol_id", "declared_at_utc"):
        before.pop(key)
        after.pop(key)
    original.base.require(before == after, "retry changed economic/source rules")


def main():
    check_unchanged_economics()
    # Dedicated process entrypoint: explicit new config/seal/root, unchanged algorithms.
    original.CONFIG, original.SEAL = CONFIG, SEAL
    original.NoRedirect = CurlSource
    original.main()


if __name__ == "__main__":
    main()
