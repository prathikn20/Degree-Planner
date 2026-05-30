import json
import logging
import re
import ollama
from typing import Optional, List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

COURSE_CODE_RE = re.compile(r'^[A-Z]{2,5}\d{2,4}[A-Z]?$')


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