import requests
from bs4 import BeautifulSoup
import logging
import re
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

logger = logging.getLogger(__name__)

# Course code pattern. Matches "COMP 210", "COMP210", "DATA 693H" etc.
# Captures dept letters and course number separately.
COURSE_CODE_RE = re.compile(r'\b([A-Z]{2,5})\s*(\d{2,4}[A-Z]?)\b')

# Cross-listed pattern: "PHIL/POLI/ECON 384" → all dept codes share one number.
# Group 1: slash-joined dept list, Group 2: course number.
CROSS_LISTED_RE = re.compile(
    r'\b([A-Z]{2,5}(?:/[A-Z]{2,5})+)\s+(\d{2,4}[A-Z]?)\b'
)

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def fetch_html(url):
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    response = session.get(url, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()
    return response.text


def _extract_from_text(text, codes, seen):
    """
    Extract all course codes from *text* into *codes*, deduplicating via *seen*.

    Handles both standard codes ("COMP 210") and cross-listed codes that share
    one number across multiple departments ("PHIL/POLI/ECON 384" → three codes).
    Cross-listed codes are prepended so they appear before any further matches.
    """
    # Cross-listed first so we capture all dept variants before the fallback
    # regex sees only the last one in a "DEPT1/DEPT2 N" string.
    for m in CROSS_LISTED_RE.finditer(text):
        number = m.group(2)
        for dept in m.group(1).split('/'):
            code = f"{dept}{number}"
            if code not in seen:
                codes.append(code)
                seen.add(code)

    # Standard single-dept codes
    for m in COURSE_CODE_RE.finditer(text):
        code = f"{m.group(1)}{m.group(2)}"
        if code not in seen:
            codes.append(code)
            seen.add(code)


def extract_course_codes(row):
    """
    Pull every valid course code out of a row.
    Priority: anchor tag text > raw cell text. Anchor codes are 100% reliable.
    """
    codes = []
    seen = set()

    # Anchor tags are course links — most reliable source
    for a in row.find_all('a'):
        _extract_from_text(a.get_text(strip=True), codes, seen)

    # If anchors had nothing, fall back to scanning cell text
    if not codes:
        for cell in row.find_all(['th', 'td']):
            if 'hourscol' in (cell.get('class') or []):
                continue
            _extract_from_text(cell.get_text(separator=' ', strip=True), codes, seen)

    return codes


def extract_credit_hours(row):
    """Return integer credit hours or None. Handles ranges like '3-4' by taking the lower bound."""
    hours_cell = row.find('td', class_='hourscol')
    if not hours_cell:
        return None
    text = hours_cell.get_text(strip=True)
    match = re.match(r'(\d+)', text)
    return int(match.group(1)) if match else None


def get_description_text(row):
    """Get human-readable text from row, excluding hours column."""
    parts = []
    for cell in row.find_all(['th', 'td']):
        if 'hourscol' in (cell.get('class') or []):
            continue
        text = cell.get_text(separator=' ', strip=True)
        if text:
            parts.append(text)
    return ' | '.join(parts)


INSTRUCTIONAL_PHRASES = [
    'chosen from', 'from the following', 'or higher', 'or above',
    'numbered', 'credit hour', 'excluding', 'no more than',
    'at least', 'select one', 'select two', 'courses from',
]

# Catches "Five additional COMP courses", "Four additional elective courses", etc.
# Won't match course titles like "Additional Topics in Computer Science" (no "courses" after).
INSTRUCTIONAL_RE = re.compile(
    r'\badditional\b.{0,40}\bcourses?\b|\belective\b.{0,20}\bcourses?\b|\bcourses?\b.{0,20}\belective',
    re.IGNORECASE
)


def _is_instructional_text(text):
    """Detect rows that are instructions/rules rather than simple course listings."""
    t = text.lower()
    if any(phrase in t for phrase in INSTRUCTIONAL_PHRASES):
        return True
    if INSTRUCTIONAL_RE.search(t):
        return True
    return False


def parse_row(row):
    """
    Convert a single <tr> into a structured row dict, or None if empty.
    Row kinds: section_header, course, or_alternative, rule_text

    Key distinction: rows can contain course code anchors AND be instructional.
    "Five additional COMP courses 420+ (excluding COMP496, COMP690)" has codes
    but is clearly rule_text, not a course row. We detect this using keywords.
    """
    classes = row.get('class') or []

    if 'areaheader' in classes:
        return {
            'kind': 'section_header',
            'title': row.get_text(strip=True)
        }

    codes = extract_course_codes(row)
    hours = extract_credit_hours(row)
    desc = get_description_text(row)

    if not desc and not codes:
        return None

    is_or = 'orclass' in classes

    # If codes are present but the row reads as an instruction, it's rule_text.
    # The embedded codes (e.g. exclusion lists) are preserved for reference.
    if codes and _is_instructional_text(desc):
        return {
            'kind': 'rule_text',
            'text': desc,
            'hours': hours,
            'embedded_codes': codes
        }

    if codes:
        return {
            'kind': 'or_alternative' if is_or else 'course',
            'codes': codes,
            'hours': hours,
            'text': desc
        }
    else:
        return {
            'kind': 'rule_text',
            'text': desc,
            'hours': hours
        }


_BOILERPLATE_RE = re.compile(
    r'^(code\s*[\|]?\s*title|total\s*hours?)\s*$'
    # "DEPT --- | Any DEPT course above N" (any combo of dashes/pipes/spaces as separator)
    r'|^[A-Z]{2,5}\s*[-| ]+any\s+\w+\s+course'
    # "Any DEPT course above N" (no leading dept code)
    r'|^any\s+[A-Z]{2,5}\s+course\b',
    re.IGNORECASE
)


def _is_real_rule(row):
    """True if row is a rule_text that carries semantic content (not Code|Title / Total Hours)."""
    if row['kind'] != 'rule_text':
        return False
    return not _BOILERPLATE_RE.match(row['text'].strip())


def _is_pure_pool_section(section):
    """A section is a 'pure pool' if it has course rows and no real rule_texts."""
    has_courses = any(r['kind'] in ('course', 'or_alternative') for r in section['rows'])
    return has_courses and not any(_is_real_rule(r) for r in section['rows'])


def _is_header_section(section):
    """A header section has no course/or_alternative rows."""
    return not any(r['kind'] in ('course', 'or_alternative') for r in section['rows'])


def _has_concentration_signal(child_sections):
    """True if any child section title suggests a campus/concentration split."""
    for s in child_sections:
        t = s['title'].lower()
        if any(kw in t for kw in ('campus', 'unc ', 'ncsu', 'nc state', 'concentration')):
            return True
    return False


def group_pool_sections(sections):
    """
    Merge consecutive child pool sections under a parent header section.

    Two grouping modes:
      A) Header (0 course rows) followed by ≥1 pure-pool sections:
         Merge all pool children's course rows into the header's rows.
         If any child title mentions a campus → append " Concentration" to header title
         so the assembler can identify it as a concentration.
      B) Header (0 course rows) followed by a section named exactly "Requirements":
         Rename header to "<title> Concentration" and adopt the Requirements section's rows.

    This collapses Allied-Science department sub-tables, Political-Science subfield pools,
    Biomedical campus splits, Business specialisation blocks, and Sample-Plan year tables
    into single manageable sections before the assembler sees them.
    """
    result = []
    i = 0
    while i < len(sections):
        sec = sections[i]

        if not _is_header_section(sec):
            result.append(sec)
            i += 1
            continue

        # Lookahead: collect consecutive pure-pool children
        j = i + 1
        children = []
        while j < len(sections) and _is_pure_pool_section(sections[j]):
            children.append(sections[j])
            j += 1

        if children:
            _GENERIC_TITLES = {'requirements', 'core requirements', 'additional requirements'}
            parent_title_lower = sec['title'].strip().lower()
            is_generic_single = (len(children) == 1
                                  and parent_title_lower in _GENERIC_TITLES)
            has_conc_signal = _has_concentration_signal(children)

            # Only merge when there are multiple children (avoids accidentally grouping a
            # standalone pool like "Experiential Education" under a dept-descriptor header
            # like "Statistics and Operations Research"), OR when the parent is a generic
            # catch-all title with exactly one descriptive child, OR concentration signal.
            if len(children) >= 2 or is_generic_single or has_conc_signal:
                pool_rows = [r for child in children
                             for r in child['rows']
                             if r['kind'] in ('course', 'or_alternative')]
                merged_rows = list(sec['rows']) + pool_rows
                title = sec['title']
                if is_generic_single:
                    title = children[0]['title']
                elif has_conc_signal:
                    title = title + ' Concentration'
                result.append({'title': title, 'rows': merged_rows})
                i = j
                continue
            # Single unrelated child — don't group, fall through to normal handling

        # Mode B: header immediately followed by a section named "Requirements" →
        # rename the pair to "<parent> Concentration" so the assembler tags it as one.
        # Guard: skip when the parent is itself a generic "Requirements" title — that
        # pattern is an empty table header that precedes the actual requirement content,
        # not a specialisation name.
        _GENERIC_PARENT_TITLES = {'requirements', 'core requirements', 'additional requirements'}
        if (j < len(sections)
                and sections[j]['title'].strip().lower() == 'requirements'
                and sec['title'].strip().lower() not in _GENERIC_PARENT_TITLES
                and not _is_header_section(sections[j])):
            child = sections[j]
            conc_title = sec['title'].strip() + ' Concentration'
            result.append({'title': conc_title, 'rows': list(child['rows'])})
            i = j + 1
            continue

        # No children found — keep header as-is (assembler will produce nothing from it)
        result.append(sec)
        i += 1

    return result


def scrape_major_requirements(url):
    """
    Returns: {
        'main_header': str,
        'sections': [{'title': str, 'rows': [parsed_row, ...]}, ...]
    }
    Each section is one logical chunk (separated by areaheader rows or table boundaries).
    """
    try:
        html = fetch_html(url)
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table', class_='sc_courselist')
    if not tables:
        logger.warning(f"No sc_courselist tables found at {url}")
        return None

    main_header = None
    sections = []
    current_section = None

    for table in tables:
        prev_h = table.find_previous(['h2', 'h3', 'h4'])
        table_header = prev_h.get_text(strip=True) if prev_h else "Requirements"
        if main_header is None:
            main_header = table_header

        # Each table is a new logical section boundary.
        if current_section and current_section['rows']:
            sections.append(current_section)
        current_section = {'title': table_header, 'rows': []}

        for tr in table.find_all('tr'):
            parsed = parse_row(tr)
            if not parsed:
                continue

            if parsed['kind'] == 'section_header':
                if current_section and current_section['rows']:
                    sections.append(current_section)
                current_section = {'title': parsed['title'], 'rows': []}
            else:
                current_section['rows'].append(parsed)

    if current_section and current_section['rows']:
        sections.append(current_section)

    # Post-process: collapse child pool sections under their parent headers
    sections = group_pool_sections(sections)

    return {'main_header': main_header, 'sections': sections}