import json
import logging
import time
import re
import os
from scraper.catalog_scraper import scrape_department
from scraper.llm_parser import parse_prerequisites_with_llm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TARGET_URL = "https://catalog.unc.edu/courses/comp/"
OUTPUT_PATH = "data/comp_e2e_test.json"
MODEL_NAME = "qwen2.5:14b" # Optimized for M4 Mac with 24GB RAM

def run_ingestion_pipeline():
    logger.info(f"Scraping {TARGET_URL}")
    
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    
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

        raw_text = data.get("raw_requisite_text", "")
        if raw_text and raw_text.strip() != "Requisites:":
            logger.info(f"Parsing: {clean_id} using {MODEL_NAME}")
            clean_prereqs = parse_prerequisites_with_llm(raw_text, model_name=MODEL_NAME)
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
            
            # Condense inner string arrays into clean single lines
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
            
        time.sleep(0.1)

    logger.info(f"Pipeline complete! Saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    run_ingestion_pipeline()