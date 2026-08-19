"""Lokalnyi CLI dlya strogoi ekstraktsii faktov iz finansovoi otchetnosti."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import fitz
import jsonschema
import torch
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator
from transformers import AutoModelForImageTextToText, AutoProcessor

# Publichnaya Apache-2.0 model, zakreplennaya po commit SHA.
MODEL_ID = "Qwen/Qwen3-VL-8B-Instruct"
# Exact reviziya: meniat bez novogo protokola nelzya.
MODEL_REVISION = "0c351dd01ed87e9c1b53cbc748cba10e6187ff3b"
# Izolirovannyi koren prilozheniya na servere.
ROOT = Path("/opt/Tester/market-lab-doc-llm")
# Vesy zagruzhayutsya tolko iz etogo kataloga, bez seti.
MODEL_DIR = ROOT / "models" / "Qwen3-VL-8B-Instruct--0c351dd0"
# Katalog vosproizvodimyh rezultatov.
RUNS_DIR = ROOT / "runs"
# Ogranichenie razmera dokazatelnoi tsitaty.
MAX_EVIDENCE_CHARS = 280
# Kanonicheskii prompt: LLM ne poluchaet kotirovki, target ili budushchie metki.
SYSTEM_PROMPT = """Ты — консервативный экстрактор фактов из финансовой отчётности.
Анализируй ТОЛЬКО изображение текущей страницы документа.
Тебе не передаются котировки, доходности, target, метки реакции рынка или будущие данные.
Не прогнозируй цену акции и не давай инвестиционных рекомендаций.
Извлеки все явные числовые финансовые показатели, которые можно подтвердить короткой
дословной цитатой с этой страницы. Не домысливай единицы или период.
Ответ — только JSON-массив без Markdown. Каждый объект имеет РОВНО поля:
metric (строка), value (число), unit (строка), period (строка), page (целое число),
evidence (короткая дословная цитата), confidence (число от 0 до 1).
Если проверяемых фактов нет, верни []. Номер страницы будет указан пользователем.
"""


class EvidenceFact(BaseModel):
    """Opisivaet odin proveriaemyi fakt s tochnoi privyazkoi k stranitse."""

    model_config = ConfigDict(extra="forbid", strict=True)

    metric: Annotated[str, Field(min_length=1, max_length=160)]
    value: float
    unit: Annotated[str, Field(min_length=1, max_length=80)]
    period: Annotated[str, Field(min_length=1, max_length=120)]
    page: Annotated[int, Field(ge=1)]
    evidence: Annotated[str, Field(min_length=1, max_length=MAX_EVIDENCE_CHARS)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        """Zapreschaet NaN i beskonechnost v chislovom znachenii."""
        if not math.isfinite(value):
            raise ValueError("value dolzhno byt konechnym")
        return value


class EvidenceList(RootModel[list[EvidenceFact]]):
    """Kornevaya schema strogo spiska dokazatelnyh faktov."""


def sha256_bytes(data: bytes) -> str:
    """Schitaet SHA-256 dlya baitovogo soderzhimogo."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Schitaet SHA-256 faila bez zagruzki vsego faila v pamyat."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: object) -> None:
    """Atomarno zapisivaet JSON i ne ostavlyaet chastichnyi rezultat."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def render_pages(path: Path, dpi: int, max_pages: int) -> list[tuple[int, Image.Image]]:
    """Chitaet izobrazhenie ili renderit PDF v RGB-stranitsy."""
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        with Image.open(path) as image:
            return [(1, image.convert("RGB").copy())]
    if suffix != ".pdf":
        raise ValueError("podderzhivayutsya tolko PDF i rastr-vye izobrazheniya")
    document = fitz.open(path)
    try:
        if document.page_count > max_pages:
            raise ValueError(f"PDF soderzhit {document.page_count} str.; limit {max_pages}")
        scale = dpi / 72.0
        pages = []
        for page_index in range(document.page_count):
            pixmap = document[page_index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            pages.append((page_index + 1, image))
        return pages
    finally:
        document.close()


def parse_json_array(text: str) -> list[dict[str, Any]]:
    """Izvlekaet edinstvennyi JSON-massiv bez ispravleniya modelnyh oshibok."""
    cleaned = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    value = json.loads(cleaned)
    if not isinstance(value, list):
        raise ValueError("otvet modeli dolzhen byt JSON-massivom")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError("kazhdyi element dolzhen byt JSON-obektom")
    return value


def validate_facts(raw: list[dict[str, Any]], page_number: int) -> list[dict[str, Any]]:
    """Proveryaet Pydantic i JSON Schema, a takzhe zapreschaet chuzhie stranitsy."""
    validated = EvidenceList.model_validate(raw)
    if any(fact.page != page_number for fact in validated.root):
        raise ValueError("model vernula fakt s nevernym nomerom stranitsy")
    dumped = validated.model_dump(mode="json")
    jsonschema.validate(instance=dumped, schema=EvidenceList.model_json_schema())
    return dumped


def load_model() -> tuple[Any, Any]:
    """Zagruzhaet BF16 model tolko iz zakreplennogo lokalnogo snapshot."""
    if not MODEL_DIR.is_dir():
        raise FileNotFoundError(f"model ne naidena: {MODEL_DIR}")
    processor = AutoProcessor.from_pretrained(MODEL_DIR, local_files_only=True)
    model = AutoModelForImageTextToText.from_pretrained(
        MODEL_DIR,
        dtype=torch.bfloat16,
        device_map="cuda:0",
        local_files_only=True,
    )
    model.eval()
    model.requires_grad_(False)
    return processor, model


def infer_page(
    processor: Any,
    model: Any,
    image: Image.Image,
    page_number: int,
    max_new_tokens: int,
) -> tuple[list[dict[str, Any]], str]:
    """Deterministichno izvlekaet fakty odnoi stranitsy bez vneshnego konteksta."""
    messages = [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT}]},
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {
                    "type": "text",
                    "text": f"Номер страницы: {page_number}. Верни проверяемые факты.",
                },
            ],
        },
    ]
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )
    inputs = {name: tensor.to(model.device) for name, tensor in inputs.items()}
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            do_sample=False,
            num_beams=1,
            max_new_tokens=max_new_tokens,
        )
    prompt_length = inputs["input_ids"].shape[1]
    raw_text = processor.batch_decode(
        generated[:, prompt_length:],
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]
    parsed = parse_json_array(raw_text)
    return validate_facts(parsed, page_number), raw_text


def dependency_versions() -> dict[str, str]:
    """Vozvrashaet versii kritichnyh bibliotek tekushchego okruzheniya."""
    names = [
        "torch",
        "transformers",
        "accelerate",
        "huggingface-hub",
        "pydantic",
        "jsonschema",
        "pymupdf",
        "pillow",
        "qwen-vl-utils",
    ]
    return {name: importlib.metadata.version(name) for name in names}


def source_hashes() -> dict[str, str]:
    """Fiksiruet hash-summy ispolnyaemogo koda i modelnogo manifesta."""
    paths = [
        Path(__file__).resolve(),
        ROOT / "run_local.sh",
        ROOT / "provenance" / "model_manifest.json",
    ]
    return {str(path): sha256_file(path) for path in paths if path.is_file()}


def run(args: argparse.Namespace) -> Path:
    """Zapuskaet ekstraktsiyu i atomarno sohranyaet rezultat s provenance."""
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=False, exist_ok=False)
    atomic_json(run_dir / "evidence.schema.json", EvidenceList.model_json_schema())
    pages = render_pages(input_path, args.dpi, args.max_pages)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    processor, model = load_model()
    all_facts: list[dict[str, Any]] = []
    raw_outputs = []
    for page_number, image in pages:
        facts, raw_text = infer_page(processor, model, image, page_number, args.max_new_tokens)
        all_facts.extend(facts)
        raw_outputs.append({"page": page_number, "text": raw_text})
    torch.cuda.synchronize()
    runtime_seconds = time.perf_counter() - started
    peak_vram_bytes = torch.cuda.max_memory_allocated()
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    trainable_parameter_count = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    atomic_json(run_dir / "evidence.json", all_facts)
    atomic_json(run_dir / "raw_model_output.json", raw_outputs)
    freeze = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "pip"), "freeze"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    freeze_path = run_dir / "requirements.freeze.txt"
    temporary_freeze = freeze_path.with_suffix(".txt.tmp")
    temporary_freeze.write_text(freeze, encoding="utf-8")
    os.replace(temporary_freeze, freeze_path)
    provenance = {
        "run_id": run_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "model_format": "BF16 safetensors",
        "parameter_count": parameter_count,
        "trainable_parameter_count": trainable_parameter_count,
        "model_market_inputs": False,
        "model_training_labels_supplied": False,
        "network_used_during_inference": False,
        "prompt_sha256": sha256_bytes(SYSTEM_PROMPT.encode("utf-8")),
        "generation": {
            "do_sample": False,
            "num_beams": 1,
            "max_new_tokens": args.max_new_tokens,
            "seed": args.seed,
        },
        "pages": len(pages),
        "facts": len(all_facts),
        "runtime_seconds": runtime_seconds,
        "peak_vram_bytes": peak_vram_bytes,
        "gpu": torch.cuda.get_device_name(0),
        "dependencies": dependency_versions(),
        "dependency_freeze_sha256": sha256_file(freeze_path),
        "source_hashes": source_hashes(),
        "schema_sha256": sha256_file(run_dir / "evidence.schema.json"),
        "evidence_sha256": sha256_file(run_dir / "evidence.json"),
    }
    atomic_json(run_dir / "provenance.json", provenance)
    print(json.dumps({"run_dir": str(run_dir), **provenance}, ensure_ascii=False))
    return run_dir


def build_parser() -> argparse.ArgumentParser:
    """Sozdaet uzkii CLI bez parametrov kotirovok ili target-metok."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="PDF ili izobrazhenie otcheta")
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--max-pages", type=int, default=32)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main() -> None:
    """Tochka vhoda lokalnogo CLI s prover-koi osnovnyh ogranichenii."""
    args = build_parser().parse_args()
    if not 72 <= args.dpi <= 300:
        raise SystemExit("dpi dolzhen byt v diapazone 72..300")
    if not 1 <= args.max_pages <= 128:
        raise SystemExit("max-pages dolzhen byt v diapazone 1..128")
    if not 64 <= args.max_new_tokens <= 4096:
        raise SystemExit("max-new-tokens dolzhen byt v diapazone 64..4096")
    run(args)


if __name__ == "__main__":
    main()
