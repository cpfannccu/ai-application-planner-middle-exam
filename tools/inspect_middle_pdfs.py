from __future__ import annotations

import json
import sys
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "中級"


def inspect_pdf(path: Path) -> dict:
    pages = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            pages.append(
                {
                    "page": page_number,
                    "width": round(float(page.width), 2),
                    "height": round(float(page.height), 2),
                    "characters": len(page.chars),
                    "words": len(page.extract_words() or []),
                    "images": len(page.images),
                    "text_preview": " ".join(text.split())[:240],
                }
            )
    return {
        "file": path.name,
        "page_count": len(pages),
        "total_characters": sum(page["characters"] for page in pages),
        "total_images": sum(page["images"] for page in pages),
        "pages": pages,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    report = {"pdf_count": len(pdfs), "pdfs": [inspect_pdf(path) for path in pdfs]}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
