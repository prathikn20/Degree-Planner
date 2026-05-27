import json
import logging
import time
import re
import os
import hashlib
from scraper.catalog_scraper import scrape_department
from scraper.llm_parser import parse_prerequisites_with_llm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TARGET_URL = "https://catalog.unc.edu/courses/comp/"
OUTPUT_PATH = "data/comp_e2e_test.json"
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

def flag_anomalies(course_id, prereq_array):
    """Analyzes the array structure and logs suspicious shapes for human review."""
    if not prereq_array:
        return
        
    flag_reason = None
    
    # Rule 1: Explicit Failure
    if prereq_array == [["MANUAL_REVIEW_NEEDED"]]:
        flag_reason = "LLM Engine Crash or Unparseable String"
        
    # Rule 2: Combinatorial Explosion (Likely invalid cross-multiplication)
    elif len(prereq_array) > 6:
        flag_reason = f"Combinatorial Explosion ({len(prereq_array)} outer AND conditions)"
        
    # Rule 3: Massive OR Pools (Likely collapsed multiple distinct pathways)
    else:
        for inner_array in prereq_array:
            if len(inner_array) > 10:
                flag_reason = f"Massive OR Pool ({len(inner_array)} choices in one block)"
                break
                
    if flag_reason:
        # Append to a running log file
        with open(LOG_PATH, "a") as log_file:
            log_file.write(f"[{course_id}] FLAG: {flag_reason}\n")
            logger.warning(f"🚩 FLAG on {course_id}: {flag_reason}")

def run_ingestion_pipeline():
    logger.info(f"Scraping {TARGET_URL}")
    
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    
    # Clear the old review log at the start of a fresh run
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
        
        # 1. CHECK MANUAL OVERRIDES FIRST (The Shield)
        if clean_id in manual_overrides:
            logger.info(f"Override Engaged 🛡️: Injecting manual data for {clean_id}")
            clean_prereqs = manual_overrides[clean_id]
            
        elif raw_text and raw_text != "Requisites:":
            text_hash = hashlib.md5(raw_text.encode('utf-8')).hexdigest()
            
            # 2. CHECK CACHE SECOND (Speed Optimization)
            if text_hash in prereq_cache:
                logger.info(f"Cache Hit ⚡: {clean_id} resolved instantly.")
                clean_prereqs = prereq_cache[text_hash]
                
            # 3. FALLBACK TO LLM (Heavy Lifting)
            else:
                logger.info(f"Cache Miss 🤖: Parsing {clean_id} using {MODEL_NAME}")
                clean_prereqs = parse_prerequisites_with_llm(raw_text, model_name=MODEL_NAME)
                
                if clean_prereqs and clean_prereqs != [["MANUAL_REVIEW_NEEDED"]]:
                    prereq_cache[text_hash] = clean_prereqs
                    save_cache(prereq_cache)
                    
            # 4. RUN ANOMALY DETECTION ON THE FINAL RESULT
            flag_anomalies(clean_id, clean_prereqs)
            
        else:
            clean_prereqs = []

        normalized_catalog[clean_id] = {
            "name": data.get("name", "").strip('. '),
            "credits": 3,
            "prerequisites": clean_prereqs,
            "corequisites": [],
            "cross_listed": [],
            "attributes": data.get("attributes", [])
        }
        
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
            logger.error(f"Failed to save checkpoint for {clean_id}: {e}")
            
        time.sleep(0.01)

    logger.info(f"Pipeline complete! Saved to {OUTPUT_PATH}")
    if os.path.exists(LOG_PATH):
        logger.warning(f"⚠️ Some courses were flagged. Check {LOG_PATH} for details.")
    else:
        logger.info(f"✅ Clean run! No structural anomalies detected.")

if __name__ == "__main__":
    run_ingestion_pipeline()