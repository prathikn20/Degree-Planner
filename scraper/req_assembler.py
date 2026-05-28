import logging
import re

logger = logging.getLogger(__name__)

# Only call the LLM if the text explicitly describes a countable rule.
# If the text doesn't match these, it's ambiguous boilerplate — drop it, don't hallucinate.
_EXPLICIT_RULE_RE = re.compile(
    r'(\d{3}\s*(or\s+higher|or\s+above|level\s+or\s+above))'   # "420 or higher"
    r'|numbered?\s+\d{3}'                                        # "numbered 420"
    r'|\d+\s+additional\b.{0,40}\bcourses?\b'                   # "five additional COMP courses"
    r'|upper.?division\s+elective',                              # "upper-division electives"
    re.IGNORECASE
)

def _is_explicit_rule(text):
    return bool(_EXPLICIT_RULE_RE.search(text))

# Strict course code validator. Reject anything else.
COURSE_CODE_RE = re.compile(r'^[A-Z]{2,5}\d{2,4}[A-Z]?$')

# Word-to-number mapping for natural language counts
WORD_NUMBERS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10
}

LIST_HEADER_PATTERNS = [
    # "chosen from", "choose from", "select from" with anything between
    re.compile(r'\b(chosen|chose|choose|select)\b.{0,30}\b(of|from)\b', re.IGNORECASE),
    # "select one", "choose two", etc.
    re.compile(r'\b(select|choose)\s+(one|two|three|four|five|six|seven|\d+)\b', re.IGNORECASE),
    # "Two ... courses ... from/chosen" with flexible gaps
    re.compile(r'\b(one|two|three|four|five|six|seven|\d+)\b.{0,40}\b(course|courses)\b.{0,20}\b(from|chosen)\b', re.IGNORECASE),
    # "(select one):" parenthetical headers used by CourseLeaf
    re.compile(r'\(select\s+\w+\)', re.IGNORECASE),
]


def classify_section_type(title):
    """Block type is determined by section title text, not by LLM."""
    t = title.lower()
    if 'concentration' in t:
        return 'concentration'
    if 'upper-division electives' in t or 'upper division electives' in t:
        return 'reference_list'
    return 'core'


def is_list_header(text):
    """Detect rows like 'Two science courses chosen from:' or 'Select one of the following:'"""
    return any(p.search(text) for p in LIST_HEADER_PATTERNS)


def extract_count_from_text(text):
    """Find the count word/digit in a list header. Returns int or None."""
    t = text.lower()
    # Try word numbers first (more specific)
    for word, num in WORD_NUMBERS.items():
        if re.search(r'\b' + word + r'\b', t):
            return num
    # Fall back to digits
    match = re.search(r'\b(\d+)\b', t)
    return int(match.group(1)) if match else None


def valid_codes_only(codes):
    return [c for c in codes if COURSE_CODE_RE.match(c)]


def assemble_section(section, rule_parser_fn):
    """
    Walks structured rows and emits a requirement block.
    rule_parser_fn(text) -> dict | None — narrow LLM call for rule_text only.

    Algorithm:
      - course row followed by N or_alternative rows -> single choice group (pick 1)
      - course row with no following or_alternative -> required_course
      - rule_text that looks like a list header -> consume following courses as list options
      - rule_text otherwise -> send to LLM rule parser
      - bare or_alternative -> skip (defensive)
    """
    title = section['title']
    rows = section['rows']
    block_type = classify_section_type(title)

    required_courses = []
    choice_groups = []
    group_counter = [0]

    def next_id(prefix):
        group_counter[0] += 1
        return f"{prefix}_{group_counter[0]}"

    i = 0
    while i < len(rows):
        row = rows[i]
        kind = row['kind']

        if kind == 'course':
            # Look ahead for OR alternatives attached to this course
            alternatives = []
            j = i + 1
            while j < len(rows) and rows[j]['kind'] == 'or_alternative':
                alternatives.extend(rows[j]['codes'])
                j += 1

            if alternatives:
                all_options = valid_codes_only(row['codes'] + alternatives)
                if all_options:
                    choice_groups.append({
                        'id': next_id('choice'),
                        'description': row.get('text', ''),
                        'type': 'explicit',
                        'courses_required': 1,
                        'options': all_options,
                        'rule': None
                    })
                i = j
            else:
                for code in valid_codes_only(row['codes']):
                    if code not in required_courses:
                        required_courses.append(code)
                i += 1

        elif kind == 'rule_text':
            text = row['text']

            if is_list_header(text):
                # Consume all immediately following course/or_alternative rows.
                # Also skip over parenthetical clarification rows (exclusion notes,
                # "with no more than X" notes) that sit between the header and the list.
                list_options = []
                j = i + 1
                while j < len(rows):
                    r = rows[j]
                    if r['kind'] in ('course', 'or_alternative'):
                        list_options.extend(r['codes'])
                        j += 1
                    elif r['kind'] == 'rule_text' and any(
                        kw in r['text'].lower()
                        for kw in ['excluding', 'except', 'not including', 'with no more', 'no more than']
                    ):
                        j += 1  # skip exclusion/clarification notes within a list block
                    else:
                        break

                list_options = valid_codes_only(list_options)
                if list_options:
                    count = extract_count_from_text(text) or 1
                    group = {
                        'id': next_id('list'),
                        'description': text,
                        'type': 'explicit',
                        'courses_required': count,
                        'options': list_options,
                        'rule': None
                    }
                    if row.get('hours'):
                        group['credits_required'] = row['hours']
                    choice_groups.append(group)
                    i = j
                else:
                    # List header with no following courses — treat as rule text
                    parsed = rule_parser_fn(text)
                    if parsed:
                        parsed['id'] = next_id('rule')
                        choice_groups.append(parsed)
                    i += 1
            else:
                # Only send to LLM if the text explicitly describes a countable rule.
                # Ambiguous boilerplate (footnotes, general notes) gets dropped.
                if _is_explicit_rule(text):
                    parsed = rule_parser_fn(text)
                    if parsed:
                        parsed['id'] = next_id('rule')
                        choice_groups.append(parsed)
                else:
                    logger.debug(f"  Skipping ambiguous rule_text (no explicit rule pattern): '{text[:60]}'")
                i += 1

        else:
            # or_alternative without preceding course — defensive skip
            logger.warning(f"  Orphan or_alternative in section '{title}': {row.get('codes')}")
            i += 1

    return {
        'block_title': title,
        'block_type': block_type,
        'required_courses': required_courses,
        'choice_groups': choice_groups
    }