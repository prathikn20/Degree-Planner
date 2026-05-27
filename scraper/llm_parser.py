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
    # Remove leading variations of "Requisites: Prerequisites,"
    clean_text = re.sub(r'^(Requisites:\s*|Prerequisites:\s*|Prerequisite:\s*)', '', text, flags=re.IGNORECASE)
    return clean_text.strip()

def normalize_course_token(token: str) -> str:
    """Final sanitation check on tokens before saving to the file."""
    token_str = str(token).upper().replace(" ", "")
    match = re.search(r'^([A-Z]{2,4}\d{3}[HL]?)$', token_str)
    return match.group(1) if match else ""

def parse_prerequisites_with_llm(raw_text: str, model_name: str = 'qwen2.5:14b') -> list[list[str]]:
    if not raw_text or raw_text.strip() == "" or raw_text.lower() == "requisites:":
        return []

    # 1. Pre-process text to remove context noise
    clean_input_text = preprocess_raw_text(raw_text)

    system_prompt = f"""
    You are an advanced university academic data extraction API. Your job is to convert raw prerequisite text into Conjunctive Normal Form (CNF): an array of arrays where outer elements are joined by AND, and inner elements are options joined by OR.

    ### TRAINING EXAMPLES:

    Example 1:
    Input text: "MATH 231 or MATH 241; a grade of C or better is required."
    Expected Output:
    {{
      "logical_analysis": "Simple choice between MATH 231 or MATH 241.",
      "prerequisites": [["MATH231", "MATH241"]]
    }}

    Example 2:
    Input text: "COMP 211 and 301; or COMP 401, 410, and 411."
    Expected Output:
    {{
      "logical_analysis": "Two distinct pathways: (COMP211 AND COMP301) OR (COMP401 AND COMP410 AND COMP411). Distribute options to satisfy CNF rules.",
      "prerequisites": [["COMP211", "COMP401"], ["COMP211", "COMP410"], ["COMP211", "COMP411"], ["COMP301", "COMP401"], ["COMP301", "COMP410"], ["COMP301", "COMP411"]]
    }}

    CRITICAL INSTRUCTIONS:
    - Distribute shared department prefixes cleanly (e.g., "COMP 211 and 301" must expand to "COMP211" and "COMP301").
    - You must fill the prerequisites array strings matching the requested token regex exactly.

    Text to parse: "{clean_input_text}"
    """

    # 2. HARD ENFORCEMENT: The 'pattern' rule forces Ollama's sampler to only generate valid course codes.
    prereq_schema = {
        "type": "object",
        "properties": {
          "logical_analysis": {
            "type": "string",
            "description": "Logical analysis expanding prefixes and distributing choices into pure CNF."
          },
          "prerequisites": {
            "type": "array",
            "items": {
              "type": "array",
              "items": {
                "type": "string",
                "pattern": "^[A-Z]{2,4}\\d{3}[HL]?$" 
              }
            }
          }
        },
        "required": ["logical_analysis", "prerequisites"]
    }

    try:
        # 3. TEMPERATURE = 0.0: Forces absolute math-driven determinism.
        response = ollama.chat(
            model=model_name, 
            messages=[
                {'role': 'system', 'content': 'You are a precise data extraction engine. Analyze logic step-by-step.'},
                {'role': 'user', 'content': system_prompt}
            ], 
            format=prereq_schema,
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
        # Fallback to llama3 if you haven't downloaded qwen2.5:14b yet
        if model_name == 'qwen2.5:14b' and "not found" in str(e).lower():
            logger.warning("Model qwen2.5:14b not found. Falling back to llama3...")
            return parse_prerequisites_with_llm(raw_text, model_name='llama3')
            
        logger.error(f"FATAL LLM CRASH on text: '{raw_text}'. Error: {e}")
        return [["MANUAL_REVIEW_NEEDED"]]