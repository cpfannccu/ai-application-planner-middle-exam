from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_name")
    parser.add_argument("page", type=int)
    parser.add_argument("--limit", type=int, default=220)
    args = parser.parse_args()

    path = ROOT / "中級" / args.pdf_name
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[args.page - 1]
        words = page.extract_words(
            x_tolerance=2,
            y_tolerance=3,
            keep_blank_chars=False,
            use_text_flow=False,
        )
        for word in words[: args.limit]:
            print(
                f"top={float(word['top']):7.2f} "
                f"x0={float(word['x0']):7.2f} "
                f"x1={float(word['x1']):7.2f} "
                f"text={word['text']}"
            )
        if page.images:
            print("\nIMAGES")
            for index, image in enumerate(page.images, start=1):
                print(
                    index,
                    {
                        "x0": round(float(image["x0"]), 2),
                        "x1": round(float(image["x1"]), 2),
                        "top": round(float(image["top"]), 2),
                        "bottom": round(float(image["bottom"]), 2),
                        "width": image.get("width"),
                        "height": image.get("height"),
                    },
                )


if __name__ == "__main__":
    main()
