import json
import logging
import re
from typing import Optional, List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

COURSE_CODE_RE = re.compile(r'^[A-Z]{2,5}\d{2,4}[A-Z]?$')

# ── Regex-based rule parser (no LLM needed) ───────────────────────────────────

_WORD_TO_NUM = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
    'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20,
}

_NON_DEPT = frozenset({
    'OR', 'AND', 'NOT', 'FOR', 'THE', 'WITH', 'FROM', 'THAT',
    'ALL', 'ANY', 'ONE', 'TWO', 'BUT', 'SEE', 'MAY', 'CAN', 'ARE',
    'NO', 'IN', 'AT', 'ON', 'AN', 'OF', 'TO', 'BY', 'AS', 'UP',
})

_DEPT_RE = re.compile(r'\b([A-Z]{2,5})\b')

# Patterns to extract minimum course number
_MIN_NUM_PATTERNS = [
    re.compile(r'\bnumbered?\s+(?:above\s+)?(\d{3})\b', re.IGNORECASE),
    re.compile(r'\b(\d{3})\s+or\s+(?:higher|above|greater)\b', re.IGNORECASE),
    re.compile(r'[(\s](\d{3})\s*or\s+(?:higher|above)\b', re.IGNORECASE),
    re.compile(r'\bat\s+(?:or\s+above\s+)?(?:the\s+)?(\d{3})\b', re.IGNORECASE),
    re.compile(r'\b(?:above|over|beyond)\s+(?:the\s+)?(\d{3})\b', re.IGNORECASE),
    re.compile(r'\b(\d{3})\s*-\s*level\b', re.IGNORECASE),
    re.compile(r'\bat\s+the\s+(\d{3})\s*level\b', re.IGNORECASE),
]

# Matches "X, Y, or Z level" to extract a number range
_LEVEL_LIST_RE = re.compile(
    r'(?:at\s+the\s+)?(\d{3})(?:\s*,\s*\d{3})*(?:\s*,?\s*or\s+(\d{3}))\s+level',
    re.IGNORECASE
)

_EXCLUDE_RE = re.compile(r'excluding\s+(.+?)(?:\)|;|$)', re.IGNORECASE)
_EXCLUDE_CODE_RE = re.compile(r'[A-Z]{2,5}\s*\d{3,4}[A-Z]?')
_CREDITS_RE = re.compile(r'\b(\d+(?:\.\d+)?)\s*credit\s*hours?\b', re.IGNORECASE)
_MIN_CREDITS_RE = re.compile(
    r'\b(?:at\s+least\s+)?(\w+)(?:\s*-\s*or\s*-?\s*more)?\s*credit\s*hour\b',
    re.IGNORECASE
)


def _rx_parse_count(text: str) -> Optional[int]:
    """
    Return the count (number of courses required) from text.

    Priority order:
      1. Leading digit  — e.g. "9 HIST courses"
      2. Leading word   — e.g. "Five additional COMP courses…" (avoids matching
                          embedded words like "three" in "three-or-more credit hours"
                          or "one" in "at least one numbered 500")
      3. First digit anywhere in text
    """
    t = text.lower()
    # 1. Leading digit
    m = re.match(r'^\s*(\d+)\b', t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 20:
            return n
    # 2. Leading word number (check each word against the start of the string)
    for word, num in _WORD_TO_NUM.items():
        if re.match(r'^\s*' + word + r'\b', t):
            return num
    # 3. Fallback: first digit anywhere (short, unambiguous integers only)
    m = re.search(r'\b(\d{1,2})\b', t)
    return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 20 else None


def _rx_parse_dept(text: str) -> Optional[str]:
    """Return the first plausible department code, or None."""
    for m in _DEPT_RE.finditer(text):
        code = m.group(1)
        if code not in _NON_DEPT and len(code) <= 5:
            return code
    return None


def parse_rule_text_regex(text: str) -> Optional[dict]:
    """
    Parse common rule-text patterns into a rule_based choice group without an LLM.

    Handles:
      • "N [additional] DEPT courses numbered X or higher [excluding ...]"
      • "N [additional] DEPT courses at the X level"
      • "N [additional] DEPT courses at the X, Y, or Z level"
      • "N [additional] DEPT courses above X"
      • "N [additional] DEPT courses" (no level filter — department only)

    Returns None when the pattern is unrecognised or the result would be
    too vague to be useful (e.g. no department AND no minimum number).
    """
    t = text.strip()

    # Don't try to parse pool-reference texts — those are handled by pool injection.
    if re.search(r'\bsee\s+(?:list|lists|requirements?)\s+below\b', t, re.IGNORECASE):
        return None
    if re.search(r'\bfrom\s+(?:the\s+)?(?:list|lists|following)\s+below\b', t, re.IGNORECASE):
        return None

    count = _rx_parse_count(t)
    if count is None:
        return None

    dept = _rx_parse_dept(t)

    # ── Number range: "at the 400, 500, or 600 level" ────────────────────────
    min_num: Optional[int] = None
    max_num: Optional[int] = None
    lm = _LEVEL_LIST_RE.search(t)
    if lm:
        all_nums = [int(n) for n in re.findall(r'\d{3}', lm.group(0)) if 100 <= int(n) <= 900]
        if all_nums:
            min_num = min(all_nums)
            max_num = max(all_nums) + 99  # e.g. 400–699 covers "400, 500, 600 level"
    else:
        # Single minimum number
        for pat in _MIN_NUM_PATTERNS:
            m = pat.search(t)
            if m:
                candidate = int(m.group(1))
                if 100 <= candidate <= 900:
                    min_num = candidate
                    break

    # Require at least a department or a minimum number to avoid useless rules
    if not dept and min_num is None:
        return None

    # ── Exclusions ────────────────────────────────────────────────────────────
    exclude: list[str] = []
    em = _EXCLUDE_RE.search(text)  # use original (mixed-case) text for dept codes
    if em:
        raw_codes = _EXCLUDE_CODE_RE.findall(em.group(1))
        exclude = [re.sub(r'\s+', '', c).upper() for c in raw_codes
                   if re.match(r'^[A-Z]{2,5}\d{3,4}[A-Z]?$', re.sub(r'\s+', '', c).upper())]

    # ── Credits ───────────────────────────────────────────────────────────────
    credits_req: Optional[int] = None
    cm = _CREDITS_RE.search(t)
    if cm:
        try:
            credits_req = int(float(cm.group(1)))
        except ValueError:
            pass

    min_credits: Optional[int] = None
    mcm = _MIN_CREDITS_RE.search(t)
    if mcm:
        raw = mcm.group(1).lower()
        min_credits = _WORD_TO_NUM.get(raw) or (int(raw) if raw.isdigit() else None)
        if min_credits and not (1 <= min_credits <= 10):
            min_credits = None

    result = {
        'description': t,
        'type': 'rule_based',
        'courses_required': count,
        'credits_required': credits_req,
        'options': [],
        'rule': {
            'department': dept,
            'min_number': min_num,
            'max_number': max_num,
            'min_credits': min_credits,
            'exclude': exclude,
        }
    }
    logger.info("  [regex] Parsed rule: %s", t[:80])
    return result


class RuleBasedCriteria(BaseModel):
    department: Optional[str] = Field(None, description="Dept prefix e.g. 'COMP'. Null if any department.")
    min_number: Optional[int] = Field(None, description="Minimum course number e.g. 420.")
    min_credits: Optional[int] = Field(None, description="Minimum credits per course.")
    exclude: List[str] = Field(default_factory=list, description="Course codes to exclude e.g. ['COMP496'].")


class RuleGroup(BaseModel):
    reasoning: str = Field(description="Brief explanation of what was extracted and why.")
    description: str = Field(description="The original rule text, copied verbatim.")
    courses_required: int = Field(description="How many courses the student must take.")
    credits_required: Optional[int] = Field(None, description="Total credits required if specified.")
    rule: RuleBasedCriteria


SYSTEM_PROMPT = """You are a university requirement rule parser. Given a single sentence describing a course selection rule, extract it into structured JSON.

### EXAMPLES:

Example 1:
Input: "Five additional three-or-more credit hour COMP courses numbered 420 or higher (excluding COMP 496, COMP 690, and COMP 692H)"
Output:
{
  "reasoning": "Count is 5. Department is COMP. Min course number is 420. Min credits per course is 3 (three-or-more). Excluded courses are COMP496, COMP690, COMP692H.",
  "description": "Five additional three-or-more credit hour COMP courses numbered 420 or higher (excluding COMP 496, COMP 690, and COMP 692H)",
  "courses_required": 5,
  "credits_required": null,
  "rule": {
    "department": "COMP",
    "min_number": 420,
    "min_credits": 3,
    "exclude": ["COMP496", "COMP690", "COMP692H"]
  }
}

Example 2:
Input: "Two additional COMP elective courses numbered 420 or higher (at least three credits each)"
Output:
{
  "reasoning": "Count is 2. Department is COMP. Min course number is 420. Min credits is 3 (at least three). No exclusions.",
  "description": "Two additional COMP elective courses numbered 420 or higher (at least three credits each)",
  "courses_required": 2,
  "credits_required": null,
  "rule": {
    "department": "COMP",
    "min_number": 420,
    "min_credits": 3,
    "exclude": []
  }
}

Example 3:
Input: "Choose six upper-division electives (see list below) OR a four-course concentration and two upper-division electives."
Output:
{
  "reasoning": "Count is 6 upper-division electives. Upper-division means 300+. No specific department. No exclusions.",
  "description": "Choose six upper-division electives (see list below) OR a four-course concentration and two upper-division electives.",
  "courses_required": 6,
  "credits_required": 18,
  "rule": {
    "department": null,
    "min_number": 300,
    "min_credits": null,
    "exclude": []
  }
}

### RULES:
- Course codes have NO spaces. "COMP 420" becomes "COMP420".
- exclude must contain ONLY course code strings, never descriptions or sentences.
- If no department is mentioned, set department to null.
- If no minimum number is mentioned, set min_number to null.
- courses_required is always a positive integer."""


def _validate(parsed: dict) -> dict | None:
    """Sanity check LLM output. Returns cleaned dict or None if unsalvageable."""
    try:
        n = int(parsed.get('courses_required', 0))
        if not (1 <= n <= 20):
            return None
    except (TypeError, ValueError):
        return None

    rule = parsed.get('rule') or {}

    dept = rule.get('department')
    if dept and not re.match(r'^[A-Z]{2,5}$', str(dept)):
        dept = None

    min_num = rule.get('min_number')
    try:
        min_num = int(min_num) if min_num is not None else None
        if min_num is not None and not (100 <= min_num <= 999):
            min_num = None
    except (TypeError, ValueError):
        min_num = None

    min_cred = rule.get('min_credits')
    try:
        min_cred = int(min_cred) if min_cred is not None else None
        if min_cred is not None and not (1 <= min_cred <= 10):
            min_cred = None
    except (TypeError, ValueError):
        min_cred = None

    exclude = [
        str(c).replace(' ', '').upper()
        for c in (rule.get('exclude') or [])
        if COURSE_CODE_RE.match(str(c).replace(' ', '').upper())
    ]

    return {
        'description': str(parsed.get('description', '')),
        'type': 'rule_based',
        'courses_required': n,
        'credits_required': parsed.get('credits_required'),
        'options': [],
        'rule': {
            'department': dept,
            'min_number': min_num,
            'min_credits': min_cred,
            'exclude': exclude,
        }
    }


def parse_rule_text(text: str, model_name: str = 'qwen2.5:32b') -> dict | None:
    """
    Parse a single natural-language rule sentence into a rule_based choice group.
    Uses few-shot examples to guide the model, same pattern as the catalog parser.
    """
    if not text or not text.strip():
        return None

    try:
        import ollama
        response = ollama.chat(
            model=model_name,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': f'Parse this rule: "{text.strip()}"'}
            ],
            format=RuleGroup.model_json_schema(),
            options={'temperature': 0.0}
        )
        raw = json.loads(response['message']['content'])
        result = _validate(raw)
        if result is None:
            logger.warning(f"Rule parser rejected output for: '{text[:80]}'")
        return result
    except Exception as e:
        logger.error(f"Rule parser crash on '{text[:60]}': {e}")
        return None