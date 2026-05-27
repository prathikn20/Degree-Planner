from __future__ import annotations
import json
import logging
import re
import ollama
from typing import List, Union, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class LogicNode(BaseModel):
    operator: str = Field(description="Must be 'AND' or 'OR'")
    operands: List[Union[str, LogicNode]] = Field(description="A list containing course codes and/or nested logic nodes.")

class CoursePrerequisitesSchema(BaseModel):
    logical_analysis: str = Field(description="A brief explanation of the prerequisite logic.")
    prerequisites: Optional[LogicNode] = Field(None, description="The root logic node representing the prerequisites. Null if none.")

def preprocess_raw_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'^(Requisites:\s*|Prerequisites:\s*|Prerequisite:\s*)', '', text, flags=re.IGNORECASE).strip()

def parse_prerequisites_with_llm(raw_text: str, model_name: str = 'qwen2.5:14b') -> dict | None:
    if not raw_text or raw_text.strip() == "" or raw_text.lower() == "requisites:":
        return None

    clean_input_text = preprocess_raw_text(raw_text)

    system_prompt = """
    You are an advanced university academic data extraction API. Your job is to read prerequisite text and map it directly into an Abstract Syntax Tree (AST) JSON structure.
    
    ### MANDATORY ARCHITECTURAL RULES:
    1. STRICT OPERATORS: The 'operator' key must ONLY ever be 'AND' or 'OR'. Never use custom logic like 'MINUS', 'EQUALS', 'GRADE', 'CONSTANT', or 'NOT'.
    2. STRICT OPERANDS: Elements inside 'operands' must be either a nested node object or a single, space-stripped, uppercase alphanumeric course code string (e.g., "COMP301", "MATH231"). 
    3. STRIP GRADE CONDITIONS: Drop all grade boundaries entirely (e.g., "grade of C or better", "passed with a B+"). Map "COMP 211 with a C" purely to the token string "COMP211". Never pass single grade letters as operands.
    4. STRIP NON-COURSE TEXT: Omit soft requirements like "permission of the instructor", "declared major", "senior standing", or "graduate status". If they are an alternative option, omit that specific option or group entirely.
    5. ELECTIVE CHOICE FLOODING: Flatten multi-course pools ("two courses from...") into a single flat 'OR' group node containing all eligible courses.
    
    ### EXAMPLES:

    Example 1:
    Input: "COMP 211 and COMP 301; a grade of C or better is required in all prerequisite courses."
    Output:
    {
      "logical_analysis": "COMP 211 and COMP 301 are required; grade options are stripped.",
      "prerequisites": {
        "operator": "AND",
        "operands": ["COMP211", "COMP301"]
      }
    }

    Example 2:
    Input: "COMP 301 or permission of the instructor."
    Output:
    {
      "logical_analysis": "Instructor permission is stripped, leaving only the course option.",
      "prerequisites": {
        "operator": "AND",
        "operands": ["COMP301"]
      }
    }
    """

    try:
        response = ollama.chat(
            model=model_name, 
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f'Text to parse: "{clean_input_text}"'}
            ], 
            format=CoursePrerequisitesSchema.model_json_schema(), 
            options={'temperature': 0.0}
        ) 
        parsed_data = json.loads(response['message']['content'])
        return parsed_data.get("prerequisites")
    except Exception as e:
        logger.error(f"FATAL LLM CRASH on text: '{raw_text}'. Error: {e}")
        return {"operator": "AND", "operands": ["MANUAL_REVIEW_NEEDED"]}