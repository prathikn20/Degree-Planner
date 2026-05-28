import re
from collections import defaultdict

import pdfplumber

_DEPT_RE = re.compile(r'^[A-Z]{2,4}$')
_NUM_RE = re.compile(r'^\d{2,4}[A-Z0-9]{0,2}L?$')
_GRADE_RE = re.compile(r'^(A[+-]?|B[+-]?|C[+-]?|D[+-]?|F|PS|P|BE|TR)$')
_TERM_SEASON_RE = re.compile(r'^(Fall|Spr|Sum|Win)$')


def _column_rows(page: "pdfplumber.page.Page", y_tolerance: int = 3) -> list[list[str]]:
    """Return token lists for each row, processing left and right columns separately."""
    mid_x = page.width / 2
    rows: list[list[str]] = []
    for x0, x1 in [(0, mid_x), (mid_x, page.width)]:
        col = page.crop((x0, 0, x1, page.height))
        words = col.extract_words()
        buckets: dict[int, list] = defaultdict(list)
        for w in words:
            y_key = round(w["top"] / y_tolerance) * y_tolerance
            buckets[y_key].append(w)
        for y in sorted(buckets):
            tokens = [w["text"] for w in sorted(buckets[y], key=lambda w: w["x0"])]
            rows.append(tokens)
    return rows


def parse_tarheel_tracker(pdf_filepath: str) -> dict:
    """Parse a UNC Tar Heel Tracker PDF into course lists.

    Returns:
        {
            "completed":   list of course codes with grades (e.g. "COMP110"),
            "in_progress": list of course codes with no grade yet,
        }

    Course codes are formatted as DEPT+NUMBER with no space (e.g. "COMP110").
    Placeholder entries like "COMP ----" and "GENR ----" are silently skipped.
    Duplicate appearances (courses listed in multiple requirement sections) are
    deduplicated; the first occurrence wins.
    """
    completed: list[str] = []
    in_progress: list[str] = []
    seen: set[str] = set()

    with pdfplumber.open(pdf_filepath) as pdf:
        for page in pdf.pages:
            for tokens in _column_rows(page):
                if len(tokens) < 4:
                    continue

                dept, num = tokens[0], tokens[1]
                if not (_DEPT_RE.match(dept) and _NUM_RE.match(num)):
                    continue

                course_code = f"{dept}{num}"
                if course_code in seen:
                    continue

                last = tokens[-1]
                if _GRADE_RE.match(last):
                    seen.add(course_code)
                    completed.append(course_code)
                elif _TERM_SEASON_RE.match(last):
                    seen.add(course_code)
                    in_progress.append(course_code)

    return {"completed": completed, "in_progress": in_progress}
