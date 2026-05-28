import json
import logging
import time
import re
import os
import hashlib
import itertools
from scraper.catalog_scraper import scrape_department
from scraper.llm_catalog_parser import parse_prerequisites_with_llm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Renamed to plural for clarity
TARGET_URLS = [
    "https://catalog.unc.edu/courses/comp/", 
    "https://catalog.unc.edu/courses/data/", 
    "https://catalog.unc.edu/courses/stor/", 
    "https://catalog.unc.edu/courses/math/",
    "https://catalog.unc.edu/courses/phys/"
]
OUTPUT_PATH = "data/course_catalog.json"
CACHE_PATH = "data/course_cache.json"
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
        
    elif operator == "CHOOSE":
        amount = node.get("amount", 1)
        # Prevent choosing more than available
        amount = min(amount, len(compiled_ops))
        combos = list(itertools.combinations(compiled_ops, amount))
        all_paths = []
        for combo in combos:
            current_paths = combo[0]
            for next_dnf in combo[1:]:
                new_paths = []
                for p1 in current_paths:
                    for p2 in next_dnf:
                        new_paths.append(list(set(p1 + p2)))
                current_paths = new_paths
            all_paths.extend(current_paths)
        return all_paths

    return []

def flag_anomalies(course_id, prereq_array):
    if not prereq_array:
        return
        
    flag_reason = None
    if prereq_array == [["MANUAL_REVIEW_NEEDED"]]:
        flag_reason = "LLM Engine Crash or Unparseable String"
    elif len(prereq_array) > 8 and course_id != "COMP523": # COMP523 intentionally has 90 paths now
        flag_reason = f"Path Explosion ({len(prereq_array)} alternative tracks compiled)"
                
    if flag_reason:
        with open(LOG_PATH, "a") as log_file:
            log_file.write(f"[{course_id}] FLAG: {flag_reason}\n")
            logger.warning(f"FLAG on {course_id}: {flag_reason}")

def run_ingestion_pipeline():
    logger.info("Starting ingestion pipeline...")
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
    
    course_cache = load_json_file(CACHE_PATH)
    manual_overrides = load_json_file(OVERRIDES_PATH)
    
    # --- BUG FIX: Loop through URLs and merge dictionaries ---
    raw_scraped_data = {}
    for url in TARGET_URLS:
        logger.info(f"Scraping {url}")
        try:
            dept_data = scrape_department(url)
            raw_scraped_data.update(dept_data)
        except Exception as e:
            logger.error(f"Scraper failed for {url}: {e}")
            
    if not raw_scraped_data:
        logger.critical("No data scraped from any URL. Exiting.")
        return
    # ---------------------------------------------------------

    normalized_catalog = {}
    cache_updated = False
    
    for course_id, data in raw_scraped_data.items():
        clean_id = course_id.strip('.')
        
        match = re.search(r'\d+', clean_id)
        if match and int(match.group()) >= 800:
            continue

        raw_text = data.get("raw_requisite_text", "").strip()
        ast_prereqs = None
        
        # 1. CHECK MANUAL OVERRIDES FIRST
        if clean_id in manual_overrides:
            logger.info(f"Override Engaged: Injecting manual data for {clean_id}")
            ast_prereqs = manual_overrides[clean_id]
            
        elif raw_text and raw_text != "Requisites:":
            text_hash = hashlib.md5(raw_text.encode('utf-8')).hexdigest()
            
            # 2. CHECK CACHE SECOND
            if text_hash in course_cache:
                ast_prereqs = course_cache[text_hash]
                
            # 3. FALLBACK TO LLM
            else:
                logger.info(f"Cache Miss: Parsing {clean_id} using {MODEL_NAME}")
                ast_prereqs = parse_prerequisites_with_llm(raw_text, model_name=MODEL_NAME)
                
                if ast_prereqs and ast_prereqs != {"operator": "AND", "operands": ["MANUAL_REVIEW_NEEDED"]}:
                    course_cache[text_hash] = ast_prereqs
                    cache_updated = True # Mark for saving later instead of every loop
                    
        # 4. COMPILE AST INTO 2D SOLVER MATRIX
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
        
    # --- BUG FIX: Save cache only once at the end ---
    if cache_updated:
        logger.info("Saving updated cache to disk...")
        save_cache(course_cache)

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
    except Exception as e:
        logger.error(f"Failed to save final catalog JSON: {e}")

    logger.info(f"Pipeline complete! Saved to {OUTPUT_PATH}")
    if os.path.exists(LOG_PATH):
        logger.warning(f"WARNING: Some courses were flagged. Check {LOG_PATH} for details.")
    else:
        logger.info(f"SUCCESS: Clean run. No structural anomalies detected.")

if __name__ == "__main__":
    run_ingestion_pipeline()