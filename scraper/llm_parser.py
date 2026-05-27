import json
import logging
import re
import ollama

logger = logging.getLogger(__name__)

def clean_llm_output(raw_output: str) -> str:
    cleaned = raw_output.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()

def preprocess_raw_text(text: str) -> str:
    """Strips out boilerplate catalog words so the LLM focuses purely on the course logic."""
    if not text:
        return ""
    clean_text = re.sub(r'^(Requisites:\s*|Prerequisites:\s*|Prerequisite:\s*)', '', text, flags=re.IGNORECASE)
    return clean_text.strip()

def normalize_course_token(token: str) -> str:
    """Final sanitation check on tokens before saving to the file. Supports any single letter suffix (e.g. P, H, L)."""
    token_str = str(token).upper().replace(" ", "")
    match = re.search(r'^([A-Z]{2,4}\d{3}[A-Z]?)$', token_str)
    return match.group(1) if match else ""

def parse_prerequisites_with_llm(raw_text: str, model_name: str = 'qwen2.5:14b') -> list[list[str]]:
    if not raw_text or raw_text.strip() == "" or raw_text.lower() == "requisites:":
        return []

    clean_input_text = preprocess_raw_text(raw_text)

    system_prompt = f"""
    You are an advanced university academic data extraction API. Convert raw prerequisite text into a valid JSON object containing a Conjunctive Normal Form (CNF) matrix under the "prerequisites" key.

    Your output MUST be a single valid JSON object containing exactly two keys:
    1. "logical_analysis": A string containing a step-by-step logical breakdown expanding shared department prefixes and evaluating nested AND/OR logic.
    2. "prerequisites": An array of arrays of strings representing the CNF matrix (outer elements joined by AND, inner choices joined by OR).

    ### CNF IMPLEMENTATION RULES:
    - Standard CNF means an AND of ORs: [ [A or B] and [C or D] ].
    - For flat alternative lists ("one of the following: A, B, or C"), group them into a single inner array: [[A, B, C]].
    - For nested pathway groups separated by an overall "OR" (e.g., "(A and B) OR (C and D)"), you MUST mathematically distribute the terms to maintain valid CNF rules. (A and B) OR (C and D) translates to: [[A, C], [A, D], [B, C], [B, D]].
    - For credit/count requirements ("Two of the following: A, B, C"), express it as all combinations required to guarantee fulfillment. To get at least 2 courses out of A, B, C, the CNF is: [[A, B, C]]. Wait, if you need 2 out of A, B, C, you must satisfy: (A or B) and (A or C) and (B or C).

    ### TRAINING EXAMPLES:

    Example 1 (Simple OR Choice):
    Input text: "MATH 231 or MATH 241; a grade of C or better is required."
    Output:
    {{
      "logical_analysis": "Simple choice between MATH 231 or MATH 241.",
      "prerequisites": [["MATH231", "MATH241"]]
    }}

    Example 2 (Strict Requirement AND Choice Pool):
    Input text: "Prerequisites, COMP 210; and COMP 283 or MATH 381."
    Output:
    {{
      "logical_analysis": "COMP 210 is strictly required, AND the student must select one discrete structures option from either COMP 283 or MATH 381.",
      "prerequisites": [["COMP210"], ["COMP283", "MATH381"]]
    }}

    Example 3 (Flat Choice Pool):
    Input text: "A C or better in one of the following courses: MATH 130, 152, or PHIL 155."
    Output:
    {{
      "logical_analysis": "The phrase 'one of the following' means any single course satisfies the requirement. Maps to a single inner OR array.",
      "prerequisites": [["MATH130", "MATH152", "PHIL155"]]
    }}

    Example 4 (Nested Pathways - REQUIRES DISTRIBUTION):
    Input text: "Prerequisites, COMP 211 and COMP 301; or COMP 401 and COMP 410."
    Output:
    {{
      "logical_analysis": "Two distinct mandatory pathways: (COMP211 AND COMP301) OR (COMP401 AND COMP410). Distribute options to format as standard CNF arrays.",
      "prerequisites": [["COMP211", "COMP401"], ["COMP211", "COMP410"], ["COMP301", "COMP401"], ["COMP301", "COMP410"]]
    }}

    Text to parse: "{clean_input_text}"
    """

    try:
        response = ollama.chat(
            model=model_name, 
            messages=[
                {'role': 'system', 'content': 'You are a precise data extraction engine. Output your response as a valid JSON object.'},
                {'role': 'user', 'content': system_prompt}
            ], 
            format='json', 
            options={'temperature': 0.0}
        ) 
        
        json_string = clean_llm_output(response['message']['content'])
        parsed_data = json.loads(json_string)
        raw_list = parsed_data.get("prerequisites", [])
        
        if isinstance(raw_list, list):
            validated_list = []
            for group in raw_list:
                if isinstance(group, list):
                    clean_group = [c for c in (normalize_course_token(item) for item in group) if c]
                    if clean_group:
                        validated_list.append(clean_group)
                else:
                    norm = normalize_course_token(group)
                    if norm:
                        validated_list.append([norm])
            return validated_list
            
        return [["MANUAL_REVIEW_NEEDED"]]
        
    except Exception as e:
        if model_name == 'qwen2.5:14b' and "not found" in str(e).lower():
            logger.warning("Model qwen2.5:14b not found. Falling back to llama3...")
            return parse_prerequisites_with_llm(raw_text, model_name='llama3')
            
        logger.error(f"FATAL LLM CRASH on text: '{raw_text}'. Error: {e}")
        return [["MANUAL_REVIEW_NEEDED"]]