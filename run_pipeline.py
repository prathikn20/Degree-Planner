import json
import logging
import time
import re
import os
import hashlib
import itertools
from scraper.catalog_scraper import scrape_department
from scraper.llm_parser import parse_prerequisites_with_llm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TARGET_URL = "https://catalog.unc.edu/courses/comp/"
OUTPUT_PATH = "data/course_catalog.json"
CACHE_PATH = "data/prereq_cache.json"
OVERRIDES_PATH = "data/overrides.json"
LOG_PATH = "data/needs_review.log"
MODEL_NAME = "qwen2.5:14b"

def load_json_file(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read {filepath}: {e}")
    return {}

def save_cache(cache_dict):
    try:
        with open(CACHE_PATH, 'w') as f:
            json.dump(cache_dict, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to write out cache file updates: {e}")

def compile_ast_to_2d_array(node) -> list:
    """
    Recursively transforms a nested Boolean logic AST object into a 2D array matrix 
    representing Disjunctive Normal Form (DNF): [[Track_1_ANDs], [Track_2_ANDs]]
    """
    if isinstance(node, str):
        token = node.strip().replace(" ", "").upper()
        if token.startswith("CSC"):
            token = "COMP" + token[3:]
        if not re.match(r'^[A-Z]{2,4}\d{2,4}[A-Z]?$', token):
            return []
        return [[token]]
    
    if not isinstance(node, dict):
        return []
        
    operator = node.get("operator", "AND").upper()
    operands = node.get("operands", [])
    
    compiled_ops = []
    for op in operands:
        dnf_op = compile_ast_to_2d_array(op)
        if dnf_op:
            compiled_ops.append(dnf_op)
            
    if not compiled_ops:
        return []
        
    if operator == "OR":
        return list(itertools.chain.from_iterable(compiled_ops))
        
    elif operator == "AND":
        current_paths = compiled_ops[0]
        for next_dnf in compiled_ops[1:]:
            new_paths = []
            for p1 in current_paths:
                for p2 in next_dnf:
                    new_paths.append(list(set(p1 + p2)))
            current_paths = new_paths
        return current_paths

    return []

def flag_anomalies(course_id, prereq_array):
    if not prereq_array:
        return
    flag_reason = None
    if prereq_array == [["MANUAL_REVIEW_NEEDED"]]:
        flag_reason = "LLM Engine Crash or Unparseable String"
    elif len(prereq_array) > 8:
        flag_reason = f"Path Explosion ({len(prereq_array)} alternative tracks compiled)"
    if flag_reason:
        with open(LOG_PATH, "a") as log_file:
            log_file.write(f"[{course_id}] FLAG: {flag_reason}\n")
            logger.warning(f"FLAG on {course_id}: {flag_reason}")

def run_ingestion_pipeline():
    logger.info(f"Scraping {TARGET_URL}")
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
    
    prereq_cache = load_json_file(CACHE_PATH)
    manual_overrides = load_json_file(OVERRIDES_PATH)
    
    try:
        raw_scraped_data = scrape_department(TARGET_URL)
    except Exception as e:
        logger.critical(f"Scraper failed: {e}")
        return

    normalized_catalog = {}
    
    for course_id, data in raw_scraped_data.items():
        clean_id = course_id.strip('.')
        match = re.search(r'\d+', clean_id)
        if match and int(match.group()) >= 800:
            continue

        raw_text = data.get("raw_requisite_text", "").strip()
        ast_prereqs = None
        
        if clean_id in manual_overrides:
            logger.info(f"Override Engaged: Injecting manual data for {clean_id}")
            ast_prereqs = manual_overrides[clean_id]
        elif raw_text and raw_text != "Requisites:":
            text_hash = hashlib.md5(raw_text.encode('utf-8')).hexdigest()
            if text_hash in prereq_cache:
                ast_prereqs = prereq_cache[text_hash]
            else:
                logger.info(f"Cache Miss: Parsing {clean_id} using {MODEL_NAME}")
                ast_prereqs = parse_prerequisites_with_llm(raw_text, model_name=MODEL_NAME)
                if ast_prereqs and ast_prereqs != {"operator": "AND", "operands": ["MANUAL_REVIEW_NEEDED"]}:
                    prereq_cache[text_hash] = ast_prereqs
                    save_cache(prereq_cache)
                    
        clean_prereqs = compile_ast_to_2d_array(ast_prereqs) if ast_prereqs else []
        flag_anomalies(clean_id, clean_prereqs)

        normalized_catalog[clean_id] = {
            "name": data.get("name", "").strip('. '),
            "credits": data.get("credits", 3),
            "prerequisites": clean_prereqs,
            "corequisites": [],
            "cross_listed": data.get("cross_listed", []),
            "attributes": data.get("attributes", [])
        }
        
    virtual_entries = {}
    for course_id, data in normalized_catalog.items():
        for cross_id in data.get("cross_listed", []):
            if cross_id in normalized_catalog:
                if course_id not in normalized_catalog[cross_id]["cross_listed"]:
                    normalized_catalog[cross_id]["cross_listed"].append(course_id)
            elif cross_id not in virtual_entries:
                virtual_entries[cross_id] = {
                    "name": f"Historical Alias for {course_id}",
                    "credits": data["credits"],
                    "prerequisites": [],
                    "corequisites": [],
                    "cross_listed": [course_id],
                    "attributes": []
                }

    normalized_catalog.update(virtual_entries)

    try:
        raw_json_str = json.dumps(normalized_catalog, indent=2)
        compact_json = re.sub(
            r'\[\s*((?:(?:[\n\s]*"[^"]*"[\n\s]*,?)+))\s*\]', 
            lambda m: '[' + re.sub(r'\s+', ' ', m.group(1)).strip() + ']', 
            raw_json_str
        )
        compact_json = re.sub(r'\[\s+\]', '[]', compact_json)

        with open(OUTPUT_PATH, 'w') as f:
            f.write(compact_json)
        logger.info(f"Pipeline complete! Saved to {OUTPUT_PATH}")
    except Exception as e:
        logger.error(f"Failed to write output catalog file: {e}")

if __name__ == "__main__":
    run_ingestion_pipeline()