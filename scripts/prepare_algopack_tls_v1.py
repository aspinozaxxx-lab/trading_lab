"""Pin the official MOEX CA for one application; no global trust or credentials."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
from pathlib import Path

import requests

CA_URL = (
    "https://raw.githubusercontent.com/moexalgo/moexalgo/"
    "f596a066e9939fa50db441a0417902875d95748c/"
    "moexalgo/certs/russian_trusted_root_ca.crt"
)
CA_PATH = Path("/etc/trading-lab/ca/moex_russian_trusted_root_ca_v1.pem")
PEM_SHA = "aa800ef345422d6158c6fafe1c06c429dbda21c3df4bb1ccb45a920ec1111399"
DER_SHA = "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31"


def validate_ca(content: bytes) -> None:
    if len(content) != 2057 or hashlib.sha256(content).hexdigest() != PEM_SHA:
        raise ValueError("official CA PEM identity mismatch")
    der = ssl.PEM_cert_to_DER_cert(content.decode("ascii"))
    if hashlib.sha256(der).hexdigest() != DER_SHA:
        raise ValueError("official CA DER identity mismatch")


def main() -> None:
    if CA_PATH.is_symlink() or CA_PATH.parent.is_symlink():
        raise ValueError("CA path must not be a symlink")
    if CA_PATH.exists():
        content = CA_PATH.read_bytes()
        validate_ca(content)
    else:
        # Fresh session: no API token, Authorization header or disabled TLS verification.
        response = requests.get(CA_URL, timeout=30, allow_redirects=False)
        if response.status_code != 200 or response.url != CA_URL:
            raise ValueError("official CA download failed")
        content = response.content
        validate_ca(content)
        CA_PATH.parent.mkdir(mode=0o755, parents=False, exist_ok=True)
        with CA_PATH.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        CA_PATH.chmod(0o644)
    context = ssl.create_default_context(cafile=str(CA_PATH))
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("TLS verification configuration invalid")
    response = requests.head(
        "https://apim.moex.com/iss/", verify=str(CA_PATH), timeout=30, allow_redirects=False,
    )
    print(json.dumps({
        "ca_path": str(CA_PATH), "pem_sha256": PEM_SHA, "der_sha256": DER_SHA,
        "tls_verified": True, "hostname_verification": True,
        "unauthenticated_head_status": response.status_code,
        "authorization_sent": False, "system_trust_modified": False,
    }))


if __name__ == "__main__":
    main()
