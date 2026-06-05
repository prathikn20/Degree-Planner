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


# Matches open elective-pool descriptions: "elective", "420 or higher", "numbered 420",
# "at the 400-level".  Used to set is_core=False on elective-pool choice groups.
_ELECTIVE_POOL_RE = re.compile(
    r'\belectives?\b'                                    # "elective" or "electives"
    r'|\d{3}\s*or\s+(?:higher|above)'                   # "420 or higher"
    r'|numbered?\s+(?:above\s+)?\d{3}'                  # "numbered 420"
    r'|at\s+the\s+\d{3}(?:\s*[-–]\s*\d{3})?\s*level',  # "at the 400-level"
    re.IGNORECASE
)


def _is_elective_pool(text: str) -> bool:
    """True when a choice-group description describes an open elective pool
    (not a specific constrained requirement)."""
    return bool(_ELECTIVE_POOL_RE.search(text))

# Strict course code validator. Reject anything else.
COURSE_CODE_RE = re.compile(r'^[A-Z]{2,5}\d{2,4}[A-Z]?$')

# ── Semantic ID generation ────────────────────────────────────────────────────

_ID_STOP = frozenset({
    'the','and','or','of','to','a','an','in','from','for','with','at','by',
    'is','are','be','was','that','this','which','have','has','not','see','list',
    'below','above','following','courses','course','credit','hours','hour',
    'total','including','required','students','also','take','must','may','can',
    'least','most','more','chosen','one','two','three','four','five','six',
    'seven','eight','nine','ten','additional','each','any','all','both',
    'either','where','select','choose','complete','fulfill','following',
    'section','area','program','major','minor','department',
})

_TYPE_WORDS = [
    ('upper.?division|upper.?level', 'upper_div'),
    (r'\belective', 'electives'),
    (r'\bgateway\b', 'gateway'),
    (r'\bseminar\b|fys\b|first.year seminar', 'seminar'),
    (r'\bcapstone\b|\bthesis\b|\bsenior project\b', 'capstone'),
    (r'\bresearch\b', 'research'),
    (r'\bfoundation', 'foundation'),
    (r'\blab\b|\blaboratory\b', 'lab'),
    (r'\bconcentration\b', 'concentration'),
    (r'\bcalculus\b|\bcalc\b', 'calculus'),
    (r'\bstatistics?\b|\bstatistical\b', 'statistics'),
    (r'\bprogramming\b', 'programming'),
    (r'\bscience\b', 'science'),
    (r'\bcore\b', 'core'),
    (r'\bwriting\b', 'writing'),
    (r'\bmath\b|mathematics', 'math'),
]


def _description_slug(description: str, block_title: str = '') -> str:
    """Convert a requirement description into a short, readable slug for use as a group ID."""
    text = description.strip()

    # Strip exclusion clauses before any pattern matching
    clean = re.sub(r'\(?\s*excluding\b.*', '', text, flags=re.IGNORECASE).strip()
    clean_lower = clean.lower()

    # ── Priority 1: DEPT + level number (highest signal) ──────────────────────

    # 1a: "DEPT [words] numbered [above] NNN"
    #     Catches: "COMP courses numbered 420", "COMP elective courses numbered 420"
    dept_numbered = re.search(
        r'\b([A-Z]{2,5})\b.{0,30}\bnumbered?\s+(?:above\s+)?(\d{3})', clean
    )
    if dept_numbered:
        dept, num = dept_numbered.group(1).lower(), dept_numbered.group(2)
        return f"{dept}_{num}_electives"

    # 1b: "DEPT (NNN or higher)" / "DEPT NNN or higher/above"
    dept_or_higher = re.search(
        r'\b([A-Z]{2,5})\b.{0,10}[(\s]*(\d{3})\s*or\s*(?:higher|above)', clean
    )
    if dept_or_higher:
        dept, num = dept_or_higher.group(1).lower(), dept_or_higher.group(2)
        return f"{dept}_{num}_electives"

    # 1c: "DEPT [words] at the NNN level" / "DEPT NNN level"
    dept_at_level = re.search(
        r'\b([A-Z]{2,5})\b.{0,30}\bat\s+the\s+(\d{3})\s*[–-]?(?:\d{3})?\s*level', clean
    )
    if not dept_at_level:
        dept_at_level = re.search(r'\b([A-Z]{2,5})\b.{0,10}\s(\d{3})\s*-?\s*level', clean)
    if dept_at_level:
        dept, num = dept_at_level.group(1).lower(), dept_at_level.group(2)
        return f"{dept}_{num}_electives"

    # 1d: Inline catalog link "DEPT NNN | Title"
    #     Catches: "MATH 233 | Calculus of Functions"
    inline_course = re.search(r'\b([A-Z]{2,5})\s+(\d{3}[A-Z]?)\s*\|', clean)
    if inline_course:
        dept, num = inline_course.group(1).lower(), inline_course.group(2)
        return f"{dept}_{num}"

    # ── Priority 2: DEPT + semantic type word ──────────────────────────────────
    NON_DEPT = {'OR', 'AND', 'NOT', 'FOR', 'THE', 'WITH', 'FROM', 'THAT',
                'ALL', 'ANY', 'ONE', 'TWO', 'BUT', 'SEE', 'MAY', 'CAN', 'ARE'}
    depts = [d for d in re.findall(r'\b([A-Z]{2,5})\b', clean) if d not in NON_DEPT]
    dept_slug = depts[0].lower() if depts else ''

    type_word = ''
    for pattern, label in _TYPE_WORDS:
        if re.search(pattern, clean_lower):
            type_word = label
            break
    if not type_word:
        # Exclude dept_slug itself and add 'credits' to stop words for fallback
        extra_stop = _ID_STOP | {'credits', 'credit', 'level', dept_slug}
        words = re.split(r'[^a-z0-9]+', clean_lower)
        kws = [w for w in words if len(w) > 3 and w not in extra_stop]
        type_word = kws[0] if kws else 'electives'

    if dept_slug:
        return f"{dept_slug}_{type_word}"

    # ── Priority 3: meaningful words from block title + type word ──────────────
    if block_title:
        title_words = re.split(r'[^a-z0-9]+', block_title.lower())
        title_kw = [w for w in title_words if len(w) > 2 and w not in _ID_STOP]
        if title_kw:
            return f"{'_'.join(title_kw[:2])}_{type_word}"

    return type_word or 'requirement'

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
    # "from the [word] list below" / "selected/chosen from the [word] list below"
    # Catches: "from the course list below", "selected from the approved list below", etc.
    re.compile(
        r'\bfrom\s+(?:(?:a|the)\s+)?(?:\w+\s+)?lists?\s+below\b',
        re.IGNORECASE
    ),
    # "at least N credit hours [of/from ...]" — credit-based pool header
    # Catches: "At least six credit hours of approved public policy electives"
    re.compile(
        r'\bat\s+least\s+(?:\w+|\d+)\s+credit\s+hours?\b',
        re.IGNORECASE
    ),
    # "N credit hours [of/from ...]" — pure credit-based header without leading count
    re.compile(
        r'^(?:\d+(?:\.\d+)?|\w+)\s+credit\s+hours?\b',
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

    Returns: 'core' | 'additional' | 'concentration' | 'reference_list'

    'additional' is for sections titled "Additional Requirements" (or similar).
    These sections contain prerequisite/support courses that are NOT subject to
    the 50% core double-counting cap between majors.
    """
    t = title.lower()

    # "Additional Requirements" — prerequisite/support courses; NOT core for the
    # double-counting cap.  Must be checked before the generic 'core' fallback.
    if re.match(r'^additional\s+requirements?\b', t):
        return 'additional'

    # --- Strong reference_list signals from title ---
    _REF_TITLE = [
        'suggestion', 'upper-division elective', 'upper division elective',
        'elective list', 'elective course list',
        'sample plan', 'plan of study',
        'course list',          # "Organismal Structure and Diversity Course List"
        'major courses',        # chemistry/stats sample-plan year listings
        # Prevent reference-pool sections whose title ends in "Pathway Courses" /
        # "Pathway List" from being mistaken for concentration sections when 'pathway'
        # is added to the concentration-keyword list below.
        'pathway courses', 'pathway list',
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
    # Handled aliases: 'concentration', ' plan', ' option', ' track',
    # 'pathway'      — e.g. "Diversity and Justice Pathway" (Geography BA)
    # 'emphasis'     — e.g. "Greek Emphasis" (Classics BA), "Areas of Emphasis" (BSBA)
    # 'specialization'/'specialisation' — international-spelling variant
    # ' strand'      — e.g. "Literature Strand"
    if any(kw in t for kw in (
        'concentration', 'pathway', 'emphasis', 'specialization', 'specialisation',
        ' plan', ' option', ' track', ' strand',
    )):
        return 'concentration'

    # --- Content-based fallback ---
    if rows is not None:
        course_count = sum(1 for r in rows if r['kind'] == 'course')
        or_alt_count = sum(1 for r in rows if r['kind'] == 'or_alternative')
        real_rule_count = _count_real_rules(rows)

        # Fast-path for extremely large elective pools (≥ 100 standalone courses,
        # no or_alternatives, no hard required signal in title).  No genuine set of
        # required courses is 100+ standalone entries — these are always elective pools
        # regardless of whether incidental rule_texts (language credits, free electives)
        # inflate real_rule_count above zero.
        _HARD_REQUIRED_FAST = r'\b(required|core|prerequisite|gateway|admission|foundation)\b'
        if (course_count >= 100 and or_alt_count == 0
                and not re.search(_HARD_REQUIRED_FAST, t)):
            return 'reference_list'

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

    # Groups from 'additional' sections are never core for double-counting purposes.
    # Everything in 'core' (or 'concentration') sections IS core — even elective pools,
    # because those still count toward the UNC 50%-cap on shared core-section courses.
    is_additional_section = (block_type == 'additional')

    def _core(_description: str = '') -> bool:
        return not is_additional_section

    required_courses = []
    choice_groups = []
    _slug_counts: dict[str, int] = {}

    def next_id(_unused_prefix: str, description: str = '') -> str:
        """Return a human-readable, collision-free group ID."""
        base = _description_slug(description, title) if description.strip() else _unused_prefix
        _slug_counts[base] = _slug_counts.get(base, 0) + 1
        n = _slug_counts[base]
        return base if n == 1 else f"{base}_{n}"

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
                    desc = row.get('text', '')
                    choice_groups.append({
                        'id': next_id('choice', desc),
                        'description': desc,
                        'type': 'explicit',
                        'courses_required': 1,
                        'options': all_options,
                        'rule': None,
                        'is_core': _core(desc),
                    })
                i = j
            else:
                codes = valid_codes_only(row['codes'])
                # Cross-listed detection: multiple codes that share the same course number
                # (e.g., PHIL384 / POLI384 / ECON384) mean "pick one of these sections".
                if len(codes) > 1:
                    numbers = {re.sub(r'^[A-Z]+', '', c) for c in codes}
                    if len(numbers) == 1:
                        desc = row.get('text', '')
                        choice_groups.append({
                            'id': next_id('choice', desc),
                            'description': desc,
                            'type': 'explicit',
                            'courses_required': 1,
                            'options': codes,
                            'rule': None,
                            'is_core': _core(desc),
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
                        # Skip short sub-category dividers / dept-qualifier texts within a
                        # list block BEFORE the exclusion-note check, so that texts like
                        # "COMP courses numbered 420–599 (excluding COMP 496)" — which contain
                        # "excluding" but are category descriptors, not standalone rules — are
                        # skipped rather than treated as exclusion notes that break the loop.
                        # Guard: texts ending with ":" are section-boundary labels (e.g.
                        # "Capstone course:") and must break the loop.
                        if (len(rtext) <= 120
                                and not is_list_header(r['text'])
                                and not rtext.endswith(':')):
                            j += 1
                        # Skip pure exclusion/clarification footnotes embedded in the list
                        # block ONLY when they are not explicit rules in their own right.
                        elif any(kw in rtext.lower() for kw in
                                 ['excluding', 'except', 'not including', 'with no more', 'no more than']):
                            if _is_explicit_rule(r['text']):
                                break  # a standalone rule — let the outer loop handle it
                            j += 1  # skip pure clarification footnote
                        else:
                            break
                    else:
                        break

                list_options = valid_codes_only(list_options)
                if list_options:
                    # Detect credit-hour headers so we can set credits_required and
                    # derive a sensible courses_required (credit_hours ÷ 3).
                    _credits_header_m = re.search(
                        r'\b(\d+(?:\.\d+)?)\s+credit\s+hours?\b'
                        r'|(?:at\s+least\s+)?(one|two|three|four|five|six|seven|eight|nine|ten)'
                        r'\s+credit\s+hours?\b',
                        text, re.IGNORECASE
                    )
                    _credits_from_header: int | None = None
                    if _credits_header_m:
                        raw = _credits_header_m.group(1) or _credits_header_m.group(2)
                        _wn = {'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,
                               'seven':7,'eight':8,'nine':9,'ten':10}
                        try:
                            _credits_from_header = int(float(raw)) if raw and raw[0].isdigit() \
                                else _wn.get((raw or '').lower())
                        except (ValueError, TypeError):
                            pass

                    if _credits_from_header:
                        # Credit-based header: set credits_required as the authoritative
                        # constraint.  courses_required is set to the credit-hours ÷ 3
                        # approximation so schema checks pass; the requirements_checker
                        # uses credits_required when present and ignores courses_required.
                        # We do NOT go through the reindex_choice_groups deletion path:
                        # that path only removes credits_required when courses_required is
                        # set as a primary (non-derived) value, so we rely on the checker's
                        # own credits_needed branch instead.
                        group = {
                            'id': next_id('list', text),
                            'description': text,
                            'type': 'explicit',
                            'courses_required': max(1, _credits_from_header // 3),
                            'credits_required': _credits_from_header,
                            'options': list_options,
                            'rule': None,
                            'is_core': _core(text),
                        }
                    else:
                        count = extract_count_from_text(text) or 1
                        # Clamp to actual option count: a "two courses" header that only
                        # captures one course before the next rule_text breaks the scan
                        # means the intent is "take this one required course" (the second
                        # is handled by a separate following group).
                        count = min(count, len(list_options))
                        group = {
                            'id': next_id('list', text),
                            'description': text,
                            'type': 'explicit',
                            'courses_required': count,
                            'options': list_options,
                            'rule': None,
                            'is_core': _core(text),
                        }
                        if row.get('hours'):
                            group['credits_required'] = row['hours']
                    choice_groups.append(group)
                    i = j
                else:
                    # List header with no following courses — treat as rule text
                    parsed = rule_parser_fn(text)
                    if parsed:
                        parsed['id'] = next_id('rule', text)
                        parsed['is_core'] = _core(text)
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
                        cat_desc = stripped.rstrip(':').strip()
                        choice_groups.append({
                            'id': next_id('list', cat_desc),
                            'description': cat_desc,
                            'type': 'explicit',
                            'courses_required': 1,
                            'options': cat_options,
                            'rule': None,
                            'is_core': _core(cat_desc),
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
                        parsed['id'] = next_id('rule', text)
                        parsed['is_core'] = _core(text)
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