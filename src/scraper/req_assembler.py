import logging
import re

logger = logging.getLogger(__name__)

# Only call the LLM if the text explicitly describes a countable rule.
_COUNT_WORDS = (r'(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten'
                r'|eleven|twelve|thirteen|fourteen|fifteen|twenty)')

_EXPLICIT_RULE_RE = re.compile(
    r'\d{3}\s*(or\s+(higher|above|greater))'                        # "420 or higher"
    r'|numbered?\s+(above\s+)?\d{3}'                                # "numbered 420" / "numbered above 520"
    r'|\b' + _COUNT_WORDS + r'\s+additional\b.{0,40}\bcourses?\b'  # "three additional COMP courses"
    r'|upper.?division\s+elective'                                  # "upper-division electives"
    # Broader catch-all: \b required so "one" inside "Capstone" does not match
    r'|\b' + _COUNT_WORDS + r'\b.{0,60}\b(?:courses?|electives?)\b'
    # N credits/hours — \b required to avoid matching mid-word (e.g. "Capstone")
    r'|\b' + _COUNT_WORDS + r'\b.{0,40}\b(?:credits?|hours?)\b'
    # "at least N courses/credits/electives"
    r'|at\s+least\s+' + _COUNT_WORDS + r'\b.{0,30}\b(?:courses?|credits?|hours?|electives?)\b',
    re.IGNORECASE
)

_BOILERPLATE_RE = re.compile(
    r'^(code\s*[\|]?\s*title|total\s*hours?|remaining\s+general\s+education)\s*$'
    # Advisory padding that never forms a requirement group
    r'|^remaining\s+general\s+education\b'
    r'|^highly\s+encouraged\b'
    r'|^(students?\s+should\s+take|students?\s+are\s+(encouraged|recommended))\b',
    re.IGNORECASE
)


def _is_explicit_rule(text):
    t = text.strip()
    if _BOILERPLATE_RE.match(t):
        return False
    return bool(_EXPLICIT_RULE_RE.search(t))

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
    re.compile(r'\b(one|two|three|four|five|six|seven|\d+)\b.{0,40}\b(course|courses)\b.{0,50}\b(from|chosen)\b', re.IGNORECASE),
    # "(select one):" parenthetical headers used by CourseLeaf
    re.compile(r'\(select\s+\w+\)', re.IGNORECASE),
    # "One of the following:", "Two of the following list:", etc.
    re.compile(r'\b(one|two|three|four|five|six|seven|\d+)\s+of\s+(the\s+)?following\b', re.IGNORECASE),
    # "see list(s) below" / "see requirements below" → consume following courses as options
    re.compile(r'\bsee\s+(lists?|requirements?)\s+below\b', re.IGNORECASE),
    # "from list(s) below" / "from the list below"
    re.compile(r'\bfrom\s+(the\s+)?(?:lists?|requirements?)\s+below\b', re.IGNORECASE),
    # "remaining credits from" / "remaining courses from"
    re.compile(r'\bremaining\s+\w+.{0,20}\bfrom\b', re.IGNORECASE),
    # "at least N credits/courses from"
    re.compile(r'\bat\s+least\s+\w+.{0,20}\b(?:credits?|hours?|courses?)\b.{0,20}\bfrom\b', re.IGNORECASE),
    # "N credits/hours from" (with count word)
    re.compile(
        r'\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b.{0,20}'
        r'\b(?:credits?|hours?)\b.{0,20}\bfrom\b',
        re.IGNORECASE
    ),
    # Parenthetical count: "Data and Computational Thinking (one course)"
    re.compile(r'\(\s*(one|two|three|four|five|\d+)\s+courses?\s*\)', re.IGNORECASE),
    # "N description course(s):" — count word at start, "course/courses" immediately before colon
    # Catches: "One principles of entrepreneurship course:", "One track course: 2"
    re.compile(r'^\s*(?:one|two|three|four|five|six|seven|\d+)\b.{0,60}\bcourses?\s*:', re.IGNORECASE),
    # "N course(s) [description]" — count word + literal "course" as next word
    # Catches: "One course emphasizing global oceanic processes:"
    re.compile(r'^\s*(?:one|two|three|four|five|six|seven|\d+)\s+courses?\b', re.IGNORECASE),
    # "Approved [elective] courses" — elective-pool headers
    # Catches: "Other Approved Elective Courses:"
    re.compile(r'\bapproved\b.{0,30}\b(?:elective\s+)?courses?\b', re.IGNORECASE),
    # "Additional courses from [Group/list]" — extra options after primary groups
    # Catches: "Additional courses from Group Three:" (Finance Concentration)
    re.compile(r'\badditional\b.{0,40}\bcourses?\b.{0,30}\bfrom\b', re.IGNORECASE),
    # "N from among/of the following [options/list]" — catches Biology "Two from among the following five options:"
    re.compile(
        r'\b(?:one|two|three|four|five|six|seven|\d+)\b.{0,30}'
        r'\b(?:from\s+among|among|of)\b.{0,30}'
        r'\b(?:following|options?|choices?|below)\b',
        re.IGNORECASE
    ),
    # Bare "One of:", "Two of:", "At least one of:", "At least two of:" used as inline
    # sub-selection headers in active (non-reference-list) sections.
    re.compile(
        r'^(?:at\s+least\s+)?(?:one|two|three|four|five|\d+)\s+of\s*:',
        re.IGNORECASE
    ),
]


_BOILERPLATE_ROW_RE = re.compile(
    r'^(code\s*[\|]?\s*title|total\s*hours?)\s*$'
    # "DEPT --- | Any DEPT course above N" (any combo of dashes/pipes/spaces as separator)
    r'|^[A-Z]{2,5}\s*[-| ]+any\s+\w+\s+course'
    # "Any DEPT course above N" (no leading department code)
    r'|^any\s+[A-Z]{2,5}\s+course\b',
    re.IGNORECASE
)

# Advisory labels whose following courses are optional (not required, not a formal choice group).
# Only "Highly encouraged …" is genuinely optional; "Students should take …" in BME means required.
_ENCOURAGED_RE = re.compile(r'^highly\s+encouraged\b', re.IGNORECASE)

# Sub-category label within a list block: short, purely alphabetic (letters/spaces/&/-/).
# Used to skip interstitial category headers like "Finance", "Marketing", "Organizational Behavior"
# when consuming course options after a list_header.
_SUBCATEGORY_RE = re.compile(r'^[A-Za-z\s/&-]+$')


def _count_real_rules(rows):
    return sum(
        1 for r in rows
        if r['kind'] == 'rule_text' and not _BOILERPLATE_ROW_RE.match(r['text'].strip())
    )


def classify_section_type(title, rows=None):
    """
    Determine block type from title (primary) and content (fallback).

    Returns: 'core' | 'concentration' | 'reference_list'
    """
    t = title.lower()

    # --- Strong reference_list signals from title ---
    _REF_TITLE = [
        'suggestion', 'upper-division elective', 'upper division elective',
        'elective list', 'elective course list',
        'sample plan', 'plan of study',
        'course list',          # "Organismal Structure and Diversity Course List"
        'major courses',        # chemistry/stats sample-plan year listings
    ]
    if any(kw in t for kw in _REF_TITLE):
        return 'reference_list'

    # Sections whose title begins with "Note:" are footnotes/clarifications
    if re.match(r'^note\s*:', t):
        return 'reference_list'

    # Sample-plan year sections ("First Year", "Second Year", etc.)
    if re.match(r'^(first|second|third|fourth|fifth)\s+(year|semester)\b', t):
        return 'reference_list'

    # "(N credit hours)" in title → pick-from pool header
    if re.search(r'\(\d+\s*credit', t):
        return 'reference_list'

    # "electives" in title, no required/core/gateway qualifier, AND no real selection rules.
    # Sections with real rules (e.g. "19.5 credit hours of business electives") are selectors,
    # not passive reference pools — they need assembler processing.
    if (re.search(r'\belectives?\b', t)
            and not re.search(r'\b(required|requirements?|core|gateway|foundation)\b', t)
            and (rows is None or _count_real_rules(rows) == 0)):
        return 'reference_list'

    # --- Concentration detection ---
    if any(kw in t for kw in ('concentration', ' plan', ' option', ' track')):
        return 'concentration'

    # --- Content-based fallback ---
    if rows is not None:
        course_count = sum(1 for r in rows if r['kind'] == 'course')
        or_alt_count = sum(1 for r in rows if r['kind'] == 'or_alternative')
        real_rule_count = _count_real_rules(rows)

        # A large pool of courses with no real selection rules → reference list.
        # Three tiers:
        #  ≥ 5 courses, no or-alts, no required/requirements → reference_list
        #  ≥ 5 courses, no or-alts, has "requirements" title → only if ≥ 25 courses
        #    (raised from 15 to avoid mis-classifying genuine small BA/BS "Requirements"
        #     sections like EXSS General BA that have 18 mandatory courses)
        #  ≥ 25 courses (any or-alt count) + no hard required signal → reference_list
        #   (handles merged pools like "Requirements" containing Organismal+Allied Science)
        if real_rule_count == 0:
            _HARD_REQUIRED = r'\b(required|core|prerequisite|gateway|admission|foundation)\b'
            _SOFT_REQUIRED = r'\brequirements?\b'
            has_hard = bool(re.search(_HARD_REQUIRED, t))
            has_soft = bool(re.search(_SOFT_REQUIRED, t))

            if course_count >= 5 and or_alt_count == 0:
                if not has_hard and not has_soft:
                    return 'reference_list'
                if not has_hard and course_count >= 25:
                    return 'reference_list'

            # For large pools even with or_alts: no genuine requirement section
            # has 25+ standalone courses with zero selection rules.
            if course_count >= 25 and not has_hard:
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
    # Allow grouping pre-pass to inject a pre-computed type
    block_type = section.get('_type') or classify_section_type(title, rows)

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
                codes = valid_codes_only(row['codes'])
                # Cross-listed detection: multiple codes that share the same course number
                # (e.g., PHIL384 / POLI384 / ECON384) mean "pick one of these sections".
                if len(codes) > 1:
                    numbers = {re.sub(r'^[A-Z]+', '', c) for c in codes}
                    if len(numbers) == 1:
                        choice_groups.append({
                            'id': next_id('choice'),
                            'description': row.get('text', ''),
                            'type': 'explicit',
                            'courses_required': 1,
                            'options': codes,
                            'rule': None
                        })
                        i += 1
                        continue
                for code in codes:
                    if code not in required_courses:
                        required_courses.append(code)
                i += 1

        elif kind == 'rule_text':
            text = row['text']

            # Advisory labels ("Highly encouraged course:", "Students should take..."):
            # skip the label AND any immediately following course rows — these are
            # optional suggestions, not requirements.
            if _ENCOURAGED_RE.match(text.strip()):
                i += 1
                while i < len(rows) and rows[i]['kind'] in ('course', 'or_alternative'):
                    i += 1
                continue

            if is_list_header(text):
                # Consume all immediately following course/or_alternative rows.
                # Also skip:
                #   • parenthetical clarification rows (exclusion notes, "with no more than X")
                #   • short purely-alphabetic sub-category labels like "Finance" or "Marketing"
                #     that organise options into named categories within a pool.
                list_options = []
                j = i + 1
                while j < len(rows):
                    r = rows[j]
                    rtext = r['text'].strip() if r['kind'] == 'rule_text' else ''
                    if r['kind'] in ('course', 'or_alternative'):
                        list_options.extend(r['codes'])
                        j += 1
                    elif r['kind'] == 'rule_text':
                        # "Total Hours" is a table footer that some catalog pages
                        # place BEFORE the course list in the HTML (unusual layout).
                        # Skip it so courses that follow are still collected.
                        # "Code | Title" and dept-descriptor patterns are true section
                        # terminators and should still break.
                        if _BOILERPLATE_ROW_RE.match(rtext):
                            if re.match(r'^total\s+hours?', rtext, re.IGNORECASE):
                                j += 1  # skip footer row, keep collecting
                                continue
                            break  # "Code | Title" and others → stop
                        # Skip exclusion/clarification notes embedded in the list block
                        if any(kw in rtext.lower() for kw in
                               ['excluding', 'except', 'not including', 'with no more', 'no more than']):
                            if _is_explicit_rule(r['text']):
                                break  # a rule in its own right — let the outer loop handle it
                            j += 1  # skip pure clarification footnotes
                        # Skip short, alphabetic-only sub-category dividers (Finance, Marketing…)
                        elif (len(rtext) <= 50
                              and not _is_explicit_rule(r['text'])
                              and not is_list_header(r['text'])
                              and _SUBCATEGORY_RE.match(rtext)):
                            j += 1
                        else:
                            break
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
                # Sub-category label detection: short rule_text ending in ":" that
                # introduces a set of options (e.g. "Cognitive:", "Clinical:").
                # Guard: must not contain course/credit/required keywords (those labels
                # are descriptors for mandatory courses, not option categories).
                stripped = text.strip()
                _LABEL_GUARD = re.compile(
                    r'\b(course|courses|credit|hours?|required|core|prerequisite|program|major)\b',
                    re.IGNORECASE
                )
                is_sub_cat = (
                    stripped.endswith(':')
                    and len(stripped) <= 60
                    and not _LABEL_GUARD.search(stripped)
                    and not _is_explicit_rule(text)
                )
                if is_sub_cat:
                    # Treat as an implicit "pick 1 from following courses" group.
                    cat_options = []
                    j = i + 1
                    while j < len(rows) and rows[j]['kind'] in ('course', 'or_alternative'):
                        cat_options.extend(rows[j]['codes'])
                        j += 1
                    cat_options = valid_codes_only(cat_options)
                    if cat_options:
                        choice_groups.append({
                            'id': next_id('list'),
                            'description': stripped.rstrip(':').strip(),
                            'type': 'explicit',
                            'courses_required': 1,
                            'options': cat_options,
                            'rule': None
                        })
                    else:
                        logger.debug(f"  Sub-cat label with no following courses: '{text[:50]}'")
                        j = i + 1  # advance by 1 only when no options found
                    i = j
                # Only send to LLM if the text explicitly describes a countable rule.
                # Ambiguous boilerplate (footnotes, general notes) gets dropped.
                elif _is_explicit_rule(text):
                    parsed = rule_parser_fn(text)
                    if parsed:
                        parsed['id'] = next_id('rule')
                        choice_groups.append(parsed)
                    i += 1
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