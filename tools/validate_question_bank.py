from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "site"
DATA_DIR = SITE_DIR / "data"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads((DATA_DIR / "questions.json").read_text(encoding="utf-8"))
    questions = payload["questions"]
    errors: list[str] = []

    if len(questions) != 300:
        errors.append(f"Expected 300 questions, found {len(questions)}")

    grouped: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
    for question in questions:
        grouped[(question["year"], question["session"], question["subject_code"])].append(question)

    for key, rows in sorted(grouped.items()):
        numbers = sorted(row["question_number"] for row in rows)
        if numbers != list(range(1, 51)):
            errors.append(f"{key}: invalid question numbers {numbers}")
        ordered = sorted(rows, key=lambda row: row["question_number"])
        for current, following in zip(ordered, ordered[1:]):
            following_prefix = following["question"][:24].strip()
            if len(following_prefix) >= 12:
                for letter in "abcd":
                    if following_prefix in current[f"option_{letter}"]:
                        errors.append(
                            f"{current['id']}: option {letter.upper()} contains the next question stem"
                        )

    boundary_questions = {
        question["question_number"]: question
        for question in grouped.get((115, 1, 3), [])
        if question["question_number"] in (48, 49, 50)
    }
    q48 = boundary_questions.get(48)
    if not q48:
        errors.append("Missing 115-1 subject 3 question 48")
    elif (
        "Automated Optical Inspection" in q48["option_d"]
        or "回答第 49~50 題" in q48["option_d"]
        or len(q48["option_d"]) > 60
    ):
        errors.append("115-1-L-S3-Q048: option D contains the 49-50 shared context")

    for number in (49, 50):
        question = boundary_questions.get(number)
        if not question:
            errors.append(f"Missing 115-1 subject 3 question {number}")
            continue
        if "Automated Optical Inspection" not in question["question"]:
            errors.append(
                f"115-1-L-S3-Q{number:03d}: missing the AOI shared context"
            )

    json_by_id = {question["id"]: question for question in questions}
    boundary_regressions = [
        (
            "114-2-L-S3-Q041",
            "option_d",
            "A_and_B.sum() / B.sum()",
            "VGG16 context leaked into question 41 option D",
        ),
        (
            "114-2-L-S3-Q042",
            "question",
            "VGG16 是由牛津大學",
            "question 42 is missing the start of the VGG16 context",
        ),
        (
            "114-2-L-S3-Q047",
            "option_d",
            "程式碼 C、程式碼 D",
            "Titanic context leaked into question 47 option D",
        ),
        (
            "114-2-L-S3-Q048",
            "question",
            "使用鐵達尼號(Titanic)資料集",
            "question 48 is missing the Titanic context",
        ),
        (
            "115-1-L-S2-Q040",
            "option_d",
            "隨機森林分類器(Random Forest Classifier)",
            "driver context leaked into question 40 option D",
        ),
        (
            "115-1-L-S2-Q041",
            "question",
            "某全球共享乘車平台",
            "question 41 is missing the driver context",
        ),
    ]
    for question_id, field, expected, message in boundary_regressions:
        question = json_by_id.get(question_id)
        if not question:
            errors.append(f"Missing {question_id}")
        elif field.startswith("option_") and question[field] != expected:
            errors.append(f"{question_id}: {message}")
        elif field == "question" and not question[field].startswith(expected):
            errors.append(f"{question_id}: {message}")

    csv_rows = []
    for path in sorted((DATA_DIR / "csv").glob("*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            csv_rows.extend(csv.DictReader(stream))
    if len(csv_rows) != len(questions):
        errors.append(f"CSV row count {len(csv_rows)} differs from JSON count {len(questions)}")

    for row in csv_rows:
        question = json_by_id.get(row["id"])
        if not question:
            errors.append(f"CSV-only question {row['id']}")
            continue
        for field in ("question", "option_a", "option_b", "option_c", "option_d", "answer"):
            if row[field] != str(question[field]):
                errors.append(f"{row['id']}: CSV/JSON mismatch in {field}")

    image_dimensions = []
    for question in questions:
        if len(question["question"]) < 12:
            errors.append(f"{question['id']}: suspiciously short question")
        for letter in "abcd":
            value = question[f"option_{letter}"]
            if not any(character.isalnum() for character in value):
                errors.append(f"{question['id']}: suspiciously short option {letter.upper()}")
        for relative_path in question["images"]:
            path = SITE_DIR / relative_path
            if not path.exists():
                errors.append(f"{question['id']}: missing image {relative_path}")
                continue
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
            if width < 80 or height < 40:
                errors.append(f"{question['id']}: suspicious image size {width}x{height}")
            image_dimensions.append((width, height, question["id"], relative_path))

    print(f"Questions: {len(questions)}")
    print(f"Papers: {len(grouped)}")
    print(f"CSV rows: {len(csv_rows)}")
    print(f"Images: {len(image_dimensions)}")
    print(f"Answers: {dict(sorted(Counter(q['answer'] for q in questions).items()))}")
    print(f"Questions with images: {sum(bool(q['images']) for q in questions)}")
    print(f"Image-only option placeholders: {sum('請參考題目圖片' in q['option_a'] for q in questions)}")
    print("Shortest questions:")
    for question in sorted(questions, key=lambda item: len(item["question"]))[:8]:
        print(f"- {question['id']} ({len(question['question'])}): {question['question'][:100]}")
    print("Smallest images:")
    for width, height, question_id, relative_path in sorted(image_dimensions)[:8]:
        print(f"- {question_id}: {width}x{height} {relative_path}")

    if errors:
        print("Validation errors:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("Validation passed")


if __name__ == "__main__":
    main()
