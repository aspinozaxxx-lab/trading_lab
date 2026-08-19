"""Izolirovannaya zagruzka zakreplennoi versii document-LLM."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download

# Publichnaya Apache-2.0 model, zakreplennaya po polnomu commit SHA.
MODEL_ID = "Qwen/Qwen3-VL-8B-Instruct"
# Neizmenyaemaya reviziya, ukazannaya v protokole eksperimenta.
MODEL_REVISION = "0c351dd01ed87e9c1b53cbc748cba10e6187ff3b"
# Izolirovannyi koren: nikakie drugie keshi servera ne ispolzuyutsya.
ROOT = Path("/opt/Tester/market-lab-doc-llm")
# Lokalnyi katalog vesov s chelovekochitaemym imenem.
MODEL_DIR = ROOT / "models" / "Qwen3-VL-8B-Instruct--0c351dd0"
# Lokalnyi HF-kesh tolko dlya etogo proekta.
HF_CACHE = ROOT / "cache" / "huggingface"


def sha256_file(path: Path) -> str:
    """Schitaet SHA-256 faila potokovo bez bolshogo potrebleniya pamyati."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: object) -> None:
    """Atomarno zapisivaet JSON v predelakh izolirovannogo kataloga."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> None:
    """Skachivaet exact snapshot i sohranyaet polnyi manifest hash-summ."""
    ROOT.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    HF_CACHE.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(HF_CACHE)
    os.environ["HF_HUB_CACHE"] = str(HF_CACHE / "hub")
    resolved = snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=MODEL_DIR,
        cache_dir=HF_CACHE / "hub",
    )
    files = []
    for path in sorted(MODEL_DIR.rglob("*")):
        if not path.is_file() or ".cache" in path.parts:
            continue
        files.append(
            {
                "path": path.relative_to(MODEL_DIR).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "model_id": MODEL_ID,
        "requested_revision": MODEL_REVISION,
        "resolved_path": str(Path(resolved).resolve()),
        "license_expected": "Apache-2.0",
        "files": files,
    }
    atomic_json(ROOT / "provenance" / "model_manifest.json", manifest)
    print(json.dumps({"status": "ok", "model_dir": resolved, "files": len(files)}))


if __name__ == "__main__":
    main()
