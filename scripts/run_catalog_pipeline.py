import json
import logging
import time
import re
import os
import sys
import hashlib
import itertools

# Allow running as `python scripts/run_catalog_pipeline.py` from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scraper.catalog_scraper import scrape_department
from src.scraper.llm_catalog_parser import parse_prerequisites_with_llm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TARGET_URLS = [
    "https://catalog.unc.edu/courses/comp/", 
    "https://catalog.unc.edu/courses/data/", 
    "https://catalog.unc.edu/courses/stor/", 
    "https://catalog.unc.edu/courses/math/",
    "https://catalog.unc.edu/courses/phys/",
    "https://catalog.unc.edu/courses/astr/",
    "https://catalog.unc.edu/courses/bioc/",
    "https://catalog.unc.edu/courses/biol/",
    "https://catalog.unc.edu/courses/bios/",
    "https://catalog.unc.edu/courses/bmme/",
    "https://catalog.unc.edu/courses/chem/",
    "https://catalog.unc.edu/courses/chip/",
    "https://catalog.unc.edu/courses/emes/",
    "https://catalog.unc.edu/courses/enec/",
    "https://catalog.unc.edu/courses/envr/",
    "https://catalog.unc.edu/courses/epid/",
    "https://catalog.unc.edu/courses/exss/",
    "https://catalog.unc.edu/courses/mcro/",
    "https://catalog.unc.edu/courses/nsci/",
    "https://catalog.unc.edu/courses/nutr/",
    "https://catalog.unc.edu/courses/sphg/",
    "https://catalog.unc.edu/courses/sphs/",

    "https://catalog.unc.edu/courses/aaad/",
    "https://catalog.unc.edu/courses/amst/",
    "https://catalog.unc.edu/courses/anth/",
    "https://catalog.unc.edu/courses/comm/",
    "https://catalog.unc.edu/courses/econ/",
    "https://catalog.unc.edu/courses/educ/",
    "https://catalog.unc.edu/courses/engl/",
    "https://catalog.unc.edu/courses/geog/",
    "https://catalog.unc.edu/courses/glbl/",
    "https://catalog.unc.edu/courses/hist/",
    "https://catalog.unc.edu/courses/ling/",
    "https://catalog.unc.edu/courses/phil/",
    "https://catalog.unc.edu/courses/plcy/",
    "https://catalog.unc.edu/courses/poli/",
    "https://catalog.unc.edu/courses/psyc/",
    "https://catalog.unc.edu/courses/pwad/",
    "https://catalog.unc.edu/courses/reli/",
    "https://catalog.unc.edu/courses/soci/",
    "https://catalog.unc.edu/courses/wgst/",

    "https://catalog.unc.edu/courses/appl/",
    "https://catalog.unc.edu/courses/busi/",
    "https://catalog.unc.edu/courses/hpm/",
    "https://catalog.unc.edu/courses/inls/",
    "https://catalog.unc.edu/courses/mejo/",
    "https://catalog.unc.edu/courses/mngt/",
    "https://catalog.unc.edu/courses/plan/"
]
OUTPUT_PATH = "data/course_catalog.json"
CACHE_PATH = "data/course_cache.json"
OVERRIDES_PATH = "data/overrides.json"
LOG_PATH = "logs/needs_review.log"
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
        tmp_path = CACHE_PATH + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(cache_dict, f, indent=2)
        os.replace(tmp_path, CACHE_PATH)
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

CHECKPOINT_INTERVAL = 50   # save catalog every N cache-hit courses


def save_catalog(catalog_dict, output_path=OUTPUT_PATH):
    """Write catalog atomically: temp file → rename, so a crash never corrupts the output."""
    try:
        raw_json_str = json.dumps(catalog_dict, indent=2)
        compact_json = re.sub(
            r'\[\s*((?:(?:[\n\s]*"[^"]*"[\n\s]*,?)+))\s*\]',
            lambda m: '[' + re.sub(r'\s+', ' ', m.group(1)).strip() + ']',
            raw_json_str
        )
        compact_json = re.sub(r'\[\s+\]', '[]', compact_json)

        tmp_path = output_path + '.tmp'
        with open(tmp_path, 'w') as f:
            f.write(compact_json)
        os.replace(tmp_path, output_path)   # atomic rename on POSIX + Windows
    except Exception as e:
        logger.error(f"Failed to save catalog: {e}")


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

    # Seed with existing catalog so a partial re-run never erases previously
    # scraped departments that aren't included in this run's TARGET_URLS.
    normalized_catalog = load_json_file(OUTPUT_PATH)
    courses_since_checkpoint = 0

    for course_id, data in raw_scraped_data.items():
        clean_id = course_id.strip('.')

        match = re.search(r'\d+', clean_id)
        if match and int(match.group()) >= 800:
            continue

        raw_text = data.get("raw_requisite_text", "").strip()
        ast_prereqs = None
        llm_used = False

        # 1. CHECK MANUAL OVERRIDES FIRST
        if clean_id in manual_overrides:
            logger.info(f"Override Engaged: Injecting manual data for {clean_id}")
            ast_prereqs = manual_overrides[clean_id]

        elif raw_text and raw_text != "Requisites:":
            text_hash = hashlib.md5(raw_text.encode('utf-8')).hexdigest()

            # 2. CHECK CACHE SECOND
            if text_hash in course_cache:
                ast_prereqs = course_cache[text_hash]

            # 3. FALLBACK TO LLM — save immediately so no work is lost on crash
            else:
                logger.info(f"Cache Miss: Parsing {clean_id} using {MODEL_NAME}")
                ast_prereqs = parse_prerequisites_with_llm(raw_text, model_name=MODEL_NAME)

                if ast_prereqs and ast_prereqs != {"operator": "AND", "operands": ["MANUAL_REVIEW_NEEDED"]}:
                    course_cache[text_hash] = ast_prereqs
                    save_cache(course_cache)
                    llm_used = True

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

        # Flush to disk after every LLM call; checkpoint every N cache-hit courses
        if llm_used:
            save_catalog(normalized_catalog)
            courses_since_checkpoint = 0
        else:
            courses_since_checkpoint += 1
            if courses_since_checkpoint >= CHECKPOINT_INTERVAL:
                save_catalog(normalized_catalog)
                courses_since_checkpoint = 0

    save_catalog(normalized_catalog)
    logger.info("Final catalog saved.")

    logger.info(f"Pipeline complete! Saved to {OUTPUT_PATH}")
    if os.path.exists(LOG_PATH):
        logger.warning(f"WARNING: Some courses were flagged. Check {LOG_PATH} for details.")
    else:
        logger.info(f"SUCCESS: Clean run. No structural anomalies detected.")

if __name__ == "__main__":
    run_ingestion_pipeline()