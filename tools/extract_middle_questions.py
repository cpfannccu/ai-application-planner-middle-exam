from __future__ import annotations

import csv
import copy
import json
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "中級"
SITE_DIR = ROOT / "site"
DATA_DIR = SITE_DIR / "data"
CSV_DIR = DATA_DIR / "csv"
ASSET_DIR = SITE_DIR / "assets" / "questions"

SUBJECTS = {
    1: "人工智慧技術應用與規劃",
    2: "大數據處理分析與應用",
    3: "機器學習技術與應用",
}

FILE_PATTERN = re.compile(
    r"(?P<year>\d{3})年(?P<session>第[一二三四五六七八九十]+次)_中級_科目"
    r"(?P<subject>[123])_(?P<subject_name>.+)_公告試題\.pdf$"
)
QUESTION_MARKER = re.compile(r"^(\d{1,2})\.$")
OPTION_MARKER = re.compile(r"[（(]([A-D])[）)]")
ANSWER_MARKER = re.compile(r"^[A-D]$")
CONTEXT_RANGE = re.compile(r"回答(?:第)?\s*(\d+)\s*[~～\-至]\s*(\d+)\s*題")
CONTEXT_START = re.compile(
    r"(?:一間遊戲市場研究公司|VGG16\b|在郵遞區號自動辨識|使用鐵達尼號|"
    r"某全球共享乘車平台|某人工智慧團隊正在開發|請依照|請根據|請依據|下圖為使用)"
)
CONTEXT_SCENARIO_START = re.compile(
    r"(?:一間遊戲市場研究公司|VGG16\s*是|在郵遞區號自動辨識|使用鐵達尼號|"
    r"某全球共享乘車平台|某人工智慧團隊正在開發)"
)
CONTENT_RIGHT = 560.0
CONTENT_TOP = 116.0
CONTENT_BOTTOM = 805.0


@dataclass
class TextLine:
    top: float
    text: str


@dataclass
class Segment:
    page_number: int
    top: float
    bottom: float
    lines: list[TextLine]
    image_boxes: list[tuple[float, float, float, float]] = field(default_factory=list)


@dataclass
class RawQuestion:
    number: int
    answer: str
    segments: list[Segment] = field(default_factory=list)


def normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    # One official PDF encodes the opening quote inside the option marker as `(A「)`.
    normalized = re.sub(r"^\(([A-D])「\)", r"(\1)「", normalized)
    return normalized


def session_number(session_label: str) -> int:
    mapping = {
        "第一次": 1,
        "第二次": 2,
        "第三次": 3,
        "第四次": 4,
        "第五次": 5,
        "第六次": 6,
        "第七次": 7,
        "第八次": 8,
        "第九次": 9,
        "第十次": 10,
    }
    return mapping[session_label]


def is_watermark(image: dict[str, Any]) -> bool:
    expected = (102.5, 492.75, 365.1, 528.8)
    actual = (
        float(image["x0"]),
        float(image["x1"]),
        float(image["top"]),
        float(image["bottom"]),
    )
    return all(abs(left - right) < 1.0 for left, right in zip(actual, expected))


def content_left_for(metadata: dict[str, Any]) -> float:
    if metadata["year"] == 114 and metadata["subject_code"] == 1:
        return 135.0
    if metadata["year"] == 114:
        return 115.0
    if metadata["subject_code"] == 2:
        return 101.0
    return 110.0


def extract_lines(page: Any, top: float, bottom: float, content_left: float) -> list[TextLine]:
    if bottom <= top + 2:
        return []
    crop = page.crop((content_left, max(CONTENT_TOP, top), CONTENT_RIGHT, min(CONTENT_BOTTOM, bottom)))
    extracted = crop.extract_text_lines(
        x_tolerance=2,
        y_tolerance=3,
        layout=False,
        strip=True,
        return_chars=False,
    )
    return [
        TextLine(float(line["top"]), normalize(line["text"]))
        for line in extracted
        if normalize(line["text"])
    ]


def image_boxes_for_segment(
    page: Any,
    top: float,
    bottom: float,
    content_left: float,
) -> list[tuple[float, float, float, float]]:
    boxes = []
    for image in page.images:
        if is_watermark(image):
            continue
        image_top = float(image["top"])
        image_bottom = float(image["bottom"])
        overlap = max(0.0, min(bottom, image_bottom) - max(top, image_top))
        image_height = max(1.0, image_bottom - image_top)
        if overlap / image_height < 0.35:
            continue
        boxes.append(
            (
                max(content_left, float(image["x0"]) - 4),
                max(top, image_top - 4),
                min(CONTENT_RIGHT, float(image["x1"]) + 4),
                min(bottom, image_bottom + 4),
            )
        )
    return boxes


def find_markers(page: Any) -> list[dict[str, Any]]:
    words = page.extract_words(x_tolerance=2, y_tolerance=3, use_text_flow=False)
    markers = []
    for word in words:
        token = normalize(word["text"])
        match = QUESTION_MARKER.match(token)
        if not match:
            continue
        x0 = float(word["x0"])
        top = float(word["top"])
        if not (80.0 <= x0 <= 126.0 and CONTENT_TOP <= top <= CONTENT_BOTTOM):
            continue
        answer_candidates = []
        for candidate in words:
            candidate_token = normalize(candidate["text"])
            if not ANSWER_MARKER.match(candidate_token):
                continue
            candidate_x0 = float(candidate["x0"])
            candidate_top = float(candidate["top"])
            if candidate_x0 >= 100.0 or abs(candidate_top - top) > 11.0:
                continue
            answer_candidates.append((abs(candidate_top - top), candidate_token))
        if not answer_candidates:
            continue
        answer = min(answer_candidates)[1]
        markers.append({"number": int(match.group(1)), "top": top, "answer": answer})
    markers.sort(key=lambda item: item["top"])
    return markers


def add_segment(
    question: RawQuestion | None,
    page: Any,
    page_number: int,
    top: float,
    bottom: float,
    content_left: float,
) -> None:
    if question is None or bottom <= top + 2:
        return
    lines = extract_lines(page, top, bottom, content_left)
    boxes = image_boxes_for_segment(page, top, bottom, content_left)
    if not lines and not boxes:
        return
    question.segments.append(Segment(page_number, top, bottom, lines, boxes))


def collect_raw_questions(pdf: Any, content_left: float) -> list[RawQuestion]:
    questions: list[RawQuestion] = []
    current: RawQuestion | None = None

    for page_number, page in enumerate(pdf.pages, start=1):
        markers = find_markers(page)
        if current is not None:
            prefix_bottom = markers[0]["top"] - 10 if markers else CONTENT_BOTTOM
            add_segment(current, page, page_number, CONTENT_TOP, prefix_bottom, content_left)

        for index, marker in enumerate(markers):
            current = RawQuestion(marker["number"], marker["answer"])
            questions.append(current)
            next_top = markers[index + 1]["top"] - 10 if index + 1 < len(markers) else CONTENT_BOTTOM
            add_segment(current, page, page_number, marker["top"] - 10, next_top, content_left)

    return questions


def join_lines(lines: list[str]) -> str:
    text = " ".join(line.strip() for line in lines if line.strip())
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u3400-\u9fff，。；：、！？（）])\s+(?=[\u3400-\u9fff，。；：、！？（）])", "", text)
    text = re.sub(r"\s+([，。；：、！？）])", r"\1", text)
    text = re.sub(r"([（])\s+", r"\1", text)
    return text


def parse_question_text(raw: RawQuestion) -> tuple[str, dict[str, str]]:
    question_lines: list[str] = []
    option_lines: dict[str, list[str]] = {letter: [] for letter in "ABCD"}
    current_option: str | None = None

    for segment in raw.segments:
        for source_line in segment.lines:
            line = normalize(source_line.text)
            matches = list(OPTION_MARKER.finditer(line))
            starts_with_option = bool(matches and not line[: matches[0].start()].strip())
            if not starts_with_option:
                if current_option is None:
                    question_lines.append(line)
                else:
                    option_lines[current_option].append(line)
                continue

            for index, match in enumerate(matches):
                current_option = match.group(1)
                text_start = match.end()
                text_end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
                fragment = line[text_start:text_end].strip()
                if fragment:
                    option_lines[current_option].append(fragment)

    question_text = join_lines(question_lines)
    options = {letter: join_lines(option_lines[letter]) for letter in "ABCD"}
    return question_text, options


def apply_shared_contexts(raw_questions: list[RawQuestion]) -> None:
    shared_contexts: list[tuple[int, int, list[Segment]]] = []
    for raw in raw_questions:
        all_text = join_lines(
            [line.text for segment in raw.segments for line in segment.lines]
        )
        range_match = CONTEXT_RANGE.search(all_text)
        if not range_match or int(range_match.group(1)) <= raw.number:
            continue

        range_segment_index = max(
            (
                index
                for index in range(len(raw.segments))
                if CONTEXT_RANGE.search(
                    join_lines(
                        [
                            line.text
                            for segment in raw.segments[index:]
                            for line in segment.lines
                        ]
                    )
                )
            ),
            default=0,
        )

        context_candidates: list[tuple[int, int, int, bool, bool]] = []
        for segment_index, segment in enumerate(raw.segments[: range_segment_index + 1]):
            for line_index, line in enumerate(segment.lines):
                start_match = CONTEXT_START.search(line.text)
                if not start_match:
                    continue
                suffix_text = join_lines(
                    [line.text[start_match.start():]]
                    + [candidate.text for candidate in segment.lines[line_index + 1 :]]
                    + [
                        candidate.text
                        for later_segment in raw.segments[segment_index + 1 :]
                        for candidate in later_segment.lines
                    ]
                )
                if CONTEXT_RANGE.search(suffix_text):
                    context_fragment = line.text[start_match.start():]
                    context_candidates.append(
                        (
                            segment_index,
                            line_index,
                            start_match.start(),
                            bool(CONTEXT_RANGE.search(context_fragment)),
                            bool(CONTEXT_SCENARIO_START.match(context_fragment)),
                        )
                    )

        if context_candidates:
            # A raw block can contain the current group's context plus one or more
            # future groups.  Prefer the latest explicit scenario opening; generic
            # "請根據…" references are only fallbacks because they can occur later
            # inside the same context.
            explicit_scenarios = [
                candidate for candidate in context_candidates if candidate[4]
            ]
            scenario_candidates = [
                candidate for candidate in context_candidates if not candidate[3]
            ]
            selected = max(
                explicit_scenarios or scenario_candidates or context_candidates
            )
            (
                start_segment_index,
                start_line_index,
                start_character_index,
                _,
                _,
            ) = selected
        else:
            start_segment_index = range_segment_index
            range_segment = raw.segments[range_segment_index]
            start_line_index = max(
                (
                    index
                    for index in range(len(range_segment.lines))
                    if CONTEXT_RANGE.search(
                        join_lines([line.text for line in range_segment.lines[index:]])
                    )
                ),
                default=0,
            )
            start_character_index = 0

        start_segment = raw.segments[start_segment_index]
        split_line = start_segment.lines[start_line_index]
        split_top = split_line.top
        kept_lines = list(start_segment.lines[:start_line_index])
        if split_line.text[:start_character_index].strip():
            kept_lines.append(
                TextLine(split_line.top, split_line.text[:start_character_index].strip())
            )
        context_lines = [
            TextLine(split_line.top, split_line.text[start_character_index:].strip())
        ] + list(start_segment.lines[start_line_index + 1 :])
        kept_boxes = [
            box for box in start_segment.image_boxes if (box[1] + box[3]) / 2 < split_top
        ]
        context_boxes = [
            box for box in start_segment.image_boxes if (box[1] + box[3]) / 2 >= split_top
        ]

        kept_segments = list(raw.segments[:start_segment_index])
        if kept_lines or kept_boxes:
            kept_segments.append(
                Segment(
                    start_segment.page_number,
                    start_segment.top,
                    split_top - 2,
                    kept_lines,
                    kept_boxes,
                )
            )
        context_segments = [
            Segment(
                start_segment.page_number,
                split_top,
                start_segment.bottom,
                context_lines,
                context_boxes,
            )
        ] + copy.deepcopy(raw.segments[start_segment_index + 1 :])
        raw.segments = kept_segments
        shared_contexts.append(
            (
                int(range_match.group(1)),
                int(range_match.group(2)),
                context_segments,
            )
        )

    by_number = {raw.number: raw for raw in raw_questions}
    for start, end, segments in shared_contexts:
        for number in range(start, end + 1):
            if number in by_number:
                by_number[number].segments = copy.deepcopy(segments) + by_number[number].segments


def option_has_content(value: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9\u3400-\u9fff]", value))


def save_crop(page: Any, bbox: tuple[float, float, float, float], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    cropped = page.crop(bbox)
    image = cropped.to_image(resolution=180, antialias=True)
    image.save(destination, format="PNG")


def render_question_images(
    pdf: Any,
    raw: RawQuestion,
    relative_dir: Path,
    options: dict[str, str],
    content_left: float,
) -> list[str]:
    actual_image_count = sum(len(segment.image_boxes) for segment in raw.segments)
    blank_option_count = sum(not option_has_content(text) for text in options.values())
    use_full_crop = actual_image_count > 0 and blank_option_count >= 2
    relative_paths: list[str] = []
    image_index = 1

    for segment in raw.segments:
        page = pdf.pages[segment.page_number - 1]
        boxes = []
        if use_full_crop and segment.image_boxes:
            boxes = [(content_left, segment.top, CONTENT_RIGHT, segment.bottom)]
        elif not use_full_crop:
            boxes = segment.image_boxes

        for box in boxes:
            filename = f"q{raw.number:03d}-{image_index:02d}.png"
            relative_path = relative_dir / filename
            save_crop(page, box, SITE_DIR / relative_path)
            relative_paths.append(relative_path.as_posix())
            image_index += 1

    return relative_paths


def parse_metadata(path: Path) -> dict[str, Any]:
    match = FILE_PATTERN.match(path.name)
    if not match:
        raise ValueError(f"Unsupported PDF filename: {path.name}")
    subject_code = int(match.group("subject"))
    return {
        "year": int(match.group("year")),
        "session": session_number(match.group("session")),
        "session_label": match.group("session"),
        "subject_code": subject_code,
        "subject_name": SUBJECTS[subject_code],
    }


def convert_pdf(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata = parse_metadata(path)
    content_left = content_left_for(metadata)
    paper_code = f"{metadata['year']}-{metadata['session']}"
    relative_asset_dir = Path("assets") / "questions" / paper_code / f"subject-{metadata['subject_code']}"
    questions: list[dict[str, Any]] = []

    with pdfplumber.open(path) as pdf:
        raw_questions = collect_raw_questions(pdf, content_left)
        apply_shared_contexts(raw_questions)
        for raw in raw_questions:
            question_text, options = parse_question_text(raw)
            images = render_question_images(pdf, raw, relative_asset_dir, options, content_left)
            for letter in "ABCD":
                if not option_has_content(options[letter]) and images:
                    options[letter] = f"選項 {letter}（請參考題目圖片）"

            source_pages = sorted({segment.page_number for segment in raw.segments})
            question_id = (
                f"{metadata['year']}-{metadata['session']}-L-"
                f"S{metadata['subject_code']}-Q{raw.number:03d}"
            )
            questions.append(
                {
                    "id": question_id,
                    "year": metadata["year"],
                    "session": metadata["session"],
                    "level": "中級",
                    "subject_code": metadata["subject_code"],
                    "subject_name": metadata["subject_name"],
                    "question_number": raw.number,
                    "question": question_text,
                    "option_a": options["A"],
                    "option_b": options["B"],
                    "option_c": options["C"],
                    "option_d": options["D"],
                    "answer": raw.answer,
                    "images": images,
                    "source_pdf": path.name,
                    "source_page": source_pages[0] if source_pages else None,
                    "source_pages": source_pages,
                    "category": "",
                    "difficulty": "",
                    "explanation": "",
                }
            )

    paper = {
        **metadata,
        "paper_code": paper_code,
        "source_pdf": path.name,
        "question_count": len(questions),
    }
    return paper, questions


CSV_COLUMNS = [
    "id",
    "year",
    "session",
    "level",
    "subject_code",
    "subject_name",
    "question_number",
    "question",
    "option_a",
    "option_b",
    "option_c",
    "option_d",
    "answer",
    "images",
    "source_pdf",
    "source_page",
    "source_pages",
    "category",
    "difficulty",
    "explanation",
]


def csv_row(question: dict[str, Any]) -> dict[str, Any]:
    row = dict(question)
    row["images"] = ";".join(question["images"])
    row["source_pages"] = ";".join(str(page) for page in question["source_pages"])
    return {column: row.get(column, "") for column in CSV_COLUMNS}


def validate(papers: list[dict[str, Any]], questions: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids = [question["id"] for question in questions]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate question IDs found")

    for paper in papers:
        paper_questions = [
            question
            for question in questions
            if question["year"] == paper["year"]
            and question["session"] == paper["session"]
            and question["subject_code"] == paper["subject_code"]
        ]
        numbers = [question["question_number"] for question in paper_questions]
        if numbers != list(range(1, 51)):
            errors.append(f"{paper['source_pdf']}: question numbers are {numbers}")

    for question in questions:
        if question["answer"] not in "ABCD":
            errors.append(f"{question['id']}: missing or invalid answer {question['answer']!r}")
        if len(question["question"]) < 5:
            errors.append(
                f"{question['id']}: question text too short {question['question']!r}; "
                f"options={[question[f'option_{letter}'][:80] for letter in 'abcd']}"
            )
        for letter in "abcd":
            if not question[f"option_{letter}"]:
                errors.append(f"{question['id']}: option {letter.upper()} is blank")
        for image in question["images"]:
            if not (SITE_DIR / image).exists():
                errors.append(f"{question['id']}: missing image {image}")
    return errors


def write_outputs(papers: list[dict[str, Any]], questions: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CSV_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": 1,
        "generated_at": date.today().isoformat(),
        "level": "中級",
        "papers": papers,
        "questions": questions,
    }
    (DATA_DIR / "questions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for paper in papers:
        paper_questions = [
            question
            for question in questions
            if question["year"] == paper["year"]
            and question["session"] == paper["session"]
            and question["subject_code"] == paper["subject_code"]
        ]
        filename = f"{paper['paper_code']}-subject-{paper['subject_code']}.csv"
        with (CSV_DIR / filename).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(csv_row(question) for question in paper_questions)

    manifest = {
        "schema_version": 1,
        "generated_at": payload["generated_at"],
        "question_count": len(questions),
        "paper_count": len(papers),
        "image_count": sum(len(question["images"]) for question in questions),
        "papers": papers,
    }
    (DATA_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if ASSET_DIR.exists():
        shutil.rmtree(ASSET_DIR)

    papers: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    for path in sorted(PDF_DIR.glob("*.pdf")):
        paper, converted = convert_pdf(path)
        papers.append(paper)
        questions.extend(converted)
        print(f"Converted {path.name}: {len(converted)} questions")

    errors = validate(papers, questions)
    if errors:
        print("\nValidation errors:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    write_outputs(papers, questions)
    print(
        f"Wrote {len(questions)} questions, {len(papers)} papers, "
        f"{sum(len(question['images']) for question in questions)} question images"
    )


if __name__ == "__main__":
    main()
