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


def extract_course_codes(row):
    """
    Pull every valid course code out of a row.
    Priority: anchor tag text > raw cell text. Anchor codes are 100% reliable.
    """
    codes = []
    seen = set()

    # Anchor tags are course links — most reliable source
    for a in row.find_all('a'):
        text = a.get_text(strip=True)
        for match in COURSE_CODE_RE.finditer(text):
            code = f"{match.group(1)}{match.group(2)}"
            if code not in seen:
                codes.append(code)
                seen.add(code)

    # If anchors had nothing, fall back to scanning cell text
    if not codes:
        for cell in row.find_all(['th', 'td']):
            if 'hourscol' in (cell.get('class') or []):
                continue
            text = cell.get_text(separator=' ', strip=True)
            for match in COURSE_CODE_RE.finditer(text):
                code = f"{match.group(1)}{match.group(2)}"
                if code not in seen:
                    codes.append(code)
                    seen.add(code)

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
        # Close whatever was accumulating from the previous table before starting fresh.
        if current_section and current_section['rows']:
            sections.append(current_section)
        current_section = {'title': table_header, 'rows': []}

        for tr in table.find_all('tr'):
            parsed = parse_row(tr)
            if not parsed:
                continue

            if parsed['kind'] == 'section_header':
                # Close previous section if it had content
                if current_section and current_section['rows']:
                    sections.append(current_section)
                current_section = {'title': parsed['title'], 'rows': []}
            else:
                current_section['rows'].append(parsed)

    if current_section and current_section['rows']:
        sections.append(current_section)

    return {'main_header': main_header, 'sections': sections}