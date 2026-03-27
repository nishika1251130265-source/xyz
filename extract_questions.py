"""
CBSE English Class 10 Question Paper Extractor
Extracts and organises questions chapter-wise from PDF question papers (2022-2025).

Usage:
    python extract_questions.py

Outputs:
    CBSE_English_Questions_Organized.md  – questions grouped by chapter
    cbse_questions_data.csv              – structured CSV data
    question_statistics.txt              – summary statistics
"""

import csv
import os
import re
import sys
from collections import defaultdict

try:
    import pdfplumber
except ImportError:
    sys.exit("pdfplumber is required. Install it with: pip install pdfplumber")

# Maximum characters retained per question in the CSV / Markdown output
MAX_QUESTION_TEXT_LENGTH = 1000
# Highest question number expected in a single paper
MAX_QUESTION_NUMBER = 20


# ---------------------------------------------------------------------------
# Year / exam-type mapping
# The second segment of the filename encodes the exam sitting:
#   1 → 2021-22 (Term 1)   2 → 2021-22 (Term 2 / 2022)
#   3 → 2022-23            4 → 2023-24
#   5 → 2024-25            6 → 2025 (Compartment)
#   S → Supplementary      C → Compartment
# ---------------------------------------------------------------------------
YEAR_MAP = {
    "1": "2022",
    "2": "2022",
    "3": "2023",
    "4": "2024",
    "5": "2025",
    "6": "2025",
    "S": "2023 (Supplementary)",
    "C": "Compartment",
}

# ---------------------------------------------------------------------------
# Section keywords – used to detect where each section begins
# ---------------------------------------------------------------------------
SECTION_PATTERNS = {
    "Reading Comprehension": [
        r"SECTION\s*[–\-:]\s*A",
        r"Reading\s+\d+\s+marks",
        r"SECTION\s+A\b",
    ],
    "Writing and Grammar": [
        r"SECTION\s*[–\-:]\s*B",
        r"Writing\s+and\s+Grammar",
        r"Writing\s*&\s*Grammar",
        r"SECTION\s+B\b",
    ],
    "Literature": [
        r"SECTION\s*[–\-:]\s*C",
        r"Literature\s+\d+\s+marks",
        r"SECTION\s+C\b",
    ],
}

# Question-type keywords
QUESTION_TYPE_PATTERNS = {
    "MCQ": [r"\bMCQ\b", r"multiple.choice", r"\(A\).*\(B\).*\(C\).*\(D\)"],
    "Short Answer": [r"\b30.{1,4}40\s+words\b", r"short\s+answer", r"\b1\s+mark\b"],
    "Long Answer": [r"\b120\s+words\b", r"long\s+answer", r"\b4\s+marks\b", r"\b8\s+marks\b"],
    "Letter/Application": [r"\bletter\b", r"\bapplication\b"],
    "Analytical Paragraph": [r"analytical\s+paragraph"],
    "Gap Fill": [r"fill\s+in\s+the\s+blank", r"complete\s+the\s+passage", r"underline\s+the\s+correct"],
    "Editing": [r"edited.*error", r"error.*correction", r"\bidentify the error\b"],
    "Reported Speech": [r"reported\s+speech", r"complete\s+the\s+passage\s+that\s+follows"],
    "Comprehension": [r"read\s+the\s+passage", r"on the basis of your understanding"],
}


def infer_year_and_set(filename: str) -> tuple[str, str, str]:
    """Return (year_label, exam_code, set_number) from a PDF filename.

    Expected filename patterns (with either hyphens or underscores as
    separators):
        2-1-1 English L & L.pdf       → year "2022", code "1", set "1"
        2_4_2_English L & L.pdf       → year "2024", code "4", set "2"
        2-S-3_English L&L.pdf         → year "2023 (Supplementary)", code "S",
                                         set "3"
        2_C_1 English Language …pdf   → year "Compartment", code "C", set "1"

    The second segment encodes the exam sitting (see YEAR_MAP for the mapping).
    """
    name = os.path.splitext(os.path.basename(filename))[0]

    # Match patterns like: 2-1-1, 2_1_1, 2-S-1, 2_C_1, 2-4-2 (...)
    m = re.search(r"2[-_]([A-Z0-9]+)[-_]([123])", name, re.IGNORECASE)
    if m:
        code = m.group(1).upper()
        set_num = m.group(2)
        year = YEAR_MAP.get(code, f"Code-{code}")
        return year, code, set_num

    return "Unknown", "?", "?"


def extract_text_from_pdf(path: str) -> str:
    """Return concatenated text from every page in the PDF."""
    try:
        with pdfplumber.open(path) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            return "\n".join(pages)
    except Exception as exc:
        print(f"  [WARN] Could not read {os.path.basename(path)}: {exc}")
        return ""


def detect_section(line: str) -> str | None:
    """Return the chapter name if this line starts a new section, else None."""
    for chapter, patterns in SECTION_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, line, re.IGNORECASE):
                return chapter
    return None


def detect_question_type(text: str) -> str:
    """Return the best-matching question type for a block of text."""
    for qtype, patterns in QUESTION_TYPE_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return qtype
    return "General"


def parse_questions(text: str) -> list[dict]:
    """
    Split the full paper text into individual question records.

    Returns a list of dicts with keys: chapter, q_number, q_type, q_text.
    """
    lines = text.splitlines()
    questions = []
    current_chapter = "General"
    current_q_num = None
    current_q_lines: list[str] = []

    # A question starts when a line begins with a number followed by a dot/bracket
    Q_START = re.compile(r"^\s*(\d{1,2})[.)\s]\s+\S")

    def flush():
        if current_q_num is not None and current_q_lines:
            q_text = " ".join(current_q_lines).strip()
            q_type = detect_question_type(q_text)
            questions.append(
                {
                    "chapter": current_chapter,
                    "q_number": current_q_num,
                    "q_type": q_type,
                    "q_text": q_text[:MAX_QUESTION_TEXT_LENGTH],
                }
            )

    for line in lines:
        # Strip page footers / headers
        if re.search(r"Page\s+\d+\s+of\s+\d+", line, re.IGNORECASE):
            continue
        if re.search(r"P\.T\.O\.?$", line.strip(), re.IGNORECASE):
            continue

        # Detect section change
        ch = detect_section(line)
        if ch:
            flush()
            current_chapter = ch
            current_q_num = None
            current_q_lines = []
            continue

        # Detect question start
        m = Q_START.match(line)
        if m:
            num = int(m.group(1))
            # Only treat as a new question if the number is reasonable (1-20)
            if 1 <= num <= MAX_QUESTION_NUMBER:
                flush()
                current_q_num = num
                current_q_lines = [line.strip()]
                continue

        if current_q_num is not None:
            current_q_lines.append(line.strip())

    flush()
    return questions


def process_all_pdfs(repo_dir: str) -> list[dict]:
    """Process every PDF in repo_dir and return a flat list of question records."""
    pdf_files = sorted(
        f for f in os.listdir(repo_dir) if f.lower().endswith(".pdf")
    )
    print(f"Found {len(pdf_files)} PDF files.")

    all_records: list[dict] = []

    for pdf_file in pdf_files:
        path = os.path.join(repo_dir, pdf_file)
        print(f"  Processing: {pdf_file}")
        year, code, set_num = infer_year_and_set(pdf_file)
        text = extract_text_from_pdf(path)
        if not text.strip():
            print(f"    [SKIP] No extractable text.")
            continue

        questions = parse_questions(text)
        for q in questions:
            all_records.append(
                {
                    "year": year,
                    "set": set_num,
                    "exam_code": code,
                    "source_file": pdf_file,
                    "chapter": q["chapter"],
                    "q_number": q["q_number"],
                    "q_type": q["q_type"],
                    "q_text": q["q_text"],
                }
            )

        print(f"    Extracted {len(questions)} questions.")

    return all_records


def write_csv(records: list[dict], path: str) -> None:
    """Write structured question data to a CSV file."""
    fieldnames = [
        "Year", "Set", "Exam Code", "Source File",
        "Chapter", "Question Number", "Question Type", "Question Text",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "Year": r["year"],
                    "Set": r["set"],
                    "Exam Code": r["exam_code"],
                    "Source File": r["source_file"],
                    "Chapter": r["chapter"],
                    "Question Number": r["q_number"],
                    "Question Type": r["q_type"],
                    "Question Text": r["q_text"],
                }
            )
    print(f"CSV written: {path}")


def write_markdown(records: list[dict], path: str) -> None:
    """Write a readable Markdown file organised by chapter then year."""
    # Group by chapter → year → list of records
    by_chapter: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        by_chapter[r["chapter"]][r["year"]].append(r)

    chapter_order = [
        "Reading Comprehension",
        "Writing and Grammar",
        "Literature",
        "General",
    ]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# CBSE English Class 10 – Previous Year Questions (2022–2025)\n\n")
        fh.write(
            "Questions extracted from official CBSE question papers and organised "
            "by chapter and year.\n\n"
        )
        fh.write("---\n\n")

        for chapter in chapter_order:
            if chapter not in by_chapter:
                continue
            fh.write(f"## {chapter}\n\n")
            years = sorted(by_chapter[chapter].keys())
            for year in years:
                recs = by_chapter[chapter][year]
                fh.write(f"### Year: {year}\n\n")
                for r in recs:
                    fh.write(
                        f"**Q{r['q_number']}** *(Set {r['set']}, {r['q_type']})*\n\n"
                    )
                    fh.write(f"{r['q_text']}\n\n")
                    fh.write("---\n\n")

        # Any chapters not in the predefined order
        for chapter in sorted(by_chapter.keys()):
            if chapter in chapter_order:
                continue
            fh.write(f"## {chapter}\n\n")
            years = sorted(by_chapter[chapter].keys())
            for year in years:
                recs = by_chapter[chapter][year]
                fh.write(f"### Year: {year}\n\n")
                for r in recs:
                    fh.write(
                        f"**Q{r['q_number']}** *(Set {r['set']}, {r['q_type']})*\n\n"
                    )
                    fh.write(f"{r['q_text']}\n\n")
                    fh.write("---\n\n")

    print(f"Markdown written: {path}")


def write_statistics(records: list[dict], pdf_count: int, path: str) -> None:
    """Write a plain-text statistics summary."""
    total = len(records)
    by_chapter: dict[str, int] = defaultdict(int)
    by_year: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)

    for r in records:
        by_chapter[r["chapter"]] += 1
        by_year[r["year"]] += 1
        by_type[r["q_type"]] += 1

    title = "CBSE English Class 10 – Question Extraction Statistics"
    lines = [
        title,
        "=" * len(title),
        "",
        f"Total PDF files processed : {pdf_count}",
        f"Total questions extracted : {total}",
        "",
        "Questions by Chapter",
        "-" * 30,
    ]
    for ch, count in sorted(by_chapter.items(), key=lambda x: -x[1]):
        lines.append(f"  {ch:<30} {count:>5}")

    lines += ["", "Questions by Year", "-" * 30]
    for yr, count in sorted(by_year.items()):
        lines.append(f"  {yr:<30} {count:>5}")

    lines += ["", "Questions by Type", "-" * 30]
    for qt, count in sorted(by_type.items(), key=lambda x: -x[1]):
        lines.append(f"  {qt:<30} {count:>5}")

    lines.append("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Statistics written: {path}")


def main() -> None:
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Repository directory: {repo_dir}\n")

    records = process_all_pdfs(repo_dir)

    pdf_count = len(
        [f for f in os.listdir(repo_dir) if f.lower().endswith(".pdf")]
    )

    if not records:
        print("\nNo questions extracted. Check that the PDFs contain selectable text.")
        return

    print(f"\nTotal questions extracted: {len(records)}\n")

    write_csv(records, os.path.join(repo_dir, "cbse_questions_data.csv"))
    write_markdown(records, os.path.join(repo_dir, "CBSE_English_Questions_Organized.md"))
    write_statistics(records, pdf_count, os.path.join(repo_dir, "question_statistics.txt"))

    print("\nDone! Output files:")
    print("  cbse_questions_data.csv")
    print("  CBSE_English_Questions_Organized.md")
    print("  question_statistics.txt")


if __name__ == "__main__":
    main()
