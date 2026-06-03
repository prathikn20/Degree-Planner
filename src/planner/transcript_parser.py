import re
from collections import defaultdict

import pdfplumber

_DEPT_RE = re.compile(r'^[A-Z]{2,4}$')
_NUM_RE = re.compile(r'^\d{2,4}[A-Z0-9]{0,2}L?$')
_GRADE_RE = re.compile(r'^(A[+-]?|B[+-]?|C[+-]?|D[+-]?|F|PS|P|BE|TR)$')
_TERM_SEASON_RE = re.compile(r'^(Fall|Spr|Sum|Win)$')
_SUMMER_SESSION_RE = re.compile(r'^(I{1,3}|IV)$')  # Roman numerals I, II, III, IV

_SEASON_LABEL = {"Fall": "Fall", "Spr": "Spring", "Sum": "SS", "Win": "Winter"}


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


def _classify_row(tokens: list[str]) -> tuple[str | None, str | None, str | None]:
    """Return (course_code, status, term_label) for a token row.

    status is "completed", "in_progress", or None if not a course row.
    term_label is e.g. "Fall", "Spring", "SS I", "SS II" (None for completed).
    """
    if len(tokens) < 4:
        return None, None, None

    dept, num = tokens[0], tokens[1]
    if not (_DEPT_RE.match(dept) and _NUM_RE.match(num)):
        return None, None, None

    course_code = f"{dept}{num}"
    last = tokens[-1]

    # Completed course: ends with a grade token
    if _GRADE_RE.match(last):
        return course_code, "completed", None

    # In-progress: ends with a bare season token (Fall / Spr / Win / Sum without session)
    if _TERM_SEASON_RE.match(last):
        label = _SEASON_LABEL.get(last, last)
        return course_code, "in_progress", label

    # In-progress summer/winter with session number: e.g. "... Sum I" or "... Sum II"
    if _SUMMER_SESSION_RE.match(last) and len(tokens) >= 2 and _TERM_SEASON_RE.match(tokens[-2]):
        season = tokens[-2]
        label = f"{_SEASON_LABEL.get(season, season)} {last}"
        return course_code, "in_progress", label

    return None, None, None


def parse_tarheel_tracker(pdf_filepath: str) -> dict:
    """Parse a UNC Tar Heel Tracker PDF into course lists.

    Returns:
        {
            "completed":    list of course codes with grades (e.g. "COMP110"),
            "in_progress":  list of course codes with no grade yet,
            "course_terms": dict mapping in-progress course code to term label
                            (e.g. "MATH233" -> "SS I", "COMP211" -> "Fall"),
        }

    Course codes are formatted as DEPT+NUMBER with no space (e.g. "COMP110").
    Placeholder entries like "COMP ----" and "GENR ----" are silently skipped.
    Duplicate appearances (courses listed in multiple requirement sections) are
    deduplicated; the first occurrence wins.
    """
    completed: list[str] = []
    in_progress: list[str] = []
    course_terms: dict[str, str] = {}
    seen: set[str] = set()

    with pdfplumber.open(pdf_filepath) as pdf:
        for page in pdf.pages:
            for tokens in _column_rows(page):
                course_code, status, term_label = _classify_row(tokens)
                if course_code is None or course_code in seen:
                    continue
                seen.add(course_code)
                if status == "completed":
                    completed.append(course_code)
                elif status == "in_progress":
                    in_progress.append(course_code)
                    if term_label:
                        course_terms[course_code] = term_label

    return {"completed": completed, "in_progress": in_progress, "course_terms": course_terms}
