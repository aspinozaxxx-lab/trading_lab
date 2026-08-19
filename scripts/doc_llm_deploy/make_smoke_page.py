"""Sozdanie sinteticheskoi russkoi stranitsy dlya GPU-smoke testa."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Izolirovannyi koren smoke-artefaktov.
ROOT = Path("/opt/Tester/market-lab-doc-llm")
# Razmer testovoi stranitsy v pikseliah.
PAGE_SIZE = (1654, 2339)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Zagruzhaet sistemnyi shrift s podderzhkoi kirillitsy."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    return ImageFont.truetype(str(path), size=size)


def main() -> None:
    """Risuet odnu kontroliruemuyu stranitsu bez realnyh kotirovok ili targetov."""
    output_dir = ROOT / "smoke"
    output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", PAGE_SIZE, "white")
    draw = ImageDraw.Draw(image)
    title = load_font(52, bold=True)
    heading = load_font(35, bold=True)
    body = load_font(31)
    small = load_font(25)
    draw.text((120, 110), 'ПАО "Тест Энерго"', fill="black", font=title)
    draw.text((120, 190), "Сокращённые результаты по МСФО", fill="black", font=heading)
    draw.text((120, 245), "за 9 месяцев 2025 года", fill="black", font=heading)
    draw.line((120, 320, 1530, 320), fill="#315b7d", width=5)
    rows = [
        ("Выручка", "148,2 млрд руб.", "+18% г/г"),
        ("Скорректированная EBITDA", "36,9 млрд руб.", "+27% г/г"),
        ("Чистая прибыль", "18,4 млрд руб.", "+31% г/г"),
        ("Капитальные затраты", "22,1 млрд руб.", "+12% г/г"),
    ]
    y = 410
    for metric, value, change in rows:
        draw.text((140, y), metric, fill="black", font=body)
        draw.text((850, y), value, fill="black", font=body)
        draw.text((1270, y), change, fill="#176b35", font=body)
        draw.line((140, y + 55, 1510, y + 55), fill="#dddddd", width=2)
        y += 115
    draw.text((140, y + 45), "Чистый долг на 30.09.2025: 52,0 млрд руб.", fill="black", font=body)
    draw.text(
        (140, y + 105),
        "Чистый долг на 31.12.2024: 61,0 млрд руб.",
        fill="black",
        font=body,
    )
    draw.rectangle((110, 1200, 1540, 1590), outline="#315b7d", width=4)
    draw.text((145, 1240), "Комментарий руководства", fill="#315b7d", font=heading)
    draw.text(
        (145, 1320), "Рост выручки поддержан увеличением объёмов продаж.", fill="black", font=body
    )
    draw.text(
        (145, 1380),
        "Компания сохранила прогноз капитальных затрат на 2025 год",
        fill="black",
        font=body,
    )
    draw.text((145, 1440), "в диапазоне 28–32 млрд руб.", fill="black", font=body)
    draw.text((120, 2180), "Дата публикации: 14 ноября 2025 года", fill="#555555", font=small)
    output = output_dir / "synthetic_ru_financial_report.png"
    temporary = output.with_suffix(".png.tmp")
    image.save(temporary, format="PNG")
    os.replace(temporary, output)
    pdf_output = output_dir / "synthetic_ru_financial_report.pdf"
    temporary_pdf = pdf_output.with_suffix(".pdf.tmp")
    image.save(temporary_pdf, format="PDF", resolution=144.0)
    os.replace(temporary_pdf, pdf_output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    metadata = {
        "synthetic": True,
        "contains_market_prices": False,
        "contains_target_labels": False,
        "image": str(output),
        "sha256": digest,
        "pdf": str(pdf_output),
        "pdf_sha256": hashlib.sha256(pdf_output.read_bytes()).hexdigest(),
    }
    metadata_path = output_dir / "synthetic_ru_financial_report.json"
    temporary_metadata = metadata_path.with_suffix(".json.tmp")
    temporary_metadata.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_metadata, metadata_path)
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == "__main__":
    main()
