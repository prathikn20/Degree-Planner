import json
import logging
import os
import time
import hashlib
import re

from scraper.req_scraper import scrape_major_requirements
from scraper.req_assembler import assemble_section
from scraper.llm_req_parser import parse_rule_text

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TARGET_TRACKS = {
    "COMP_BS": "https://catalog.unc.edu/undergraduate/programs-study/computer-science-major-bs/",
    "COMP_BA": "https://catalog.unc.edu/undergraduate/programs-study/computer-science-major-ba/",
    "DATA_BS": "https://catalog.unc.edu/undergraduate/programs-study/data-science-major-bs/"
}

OUTPUT_PATH = "data/degree_requirements.json"
req_cache_PATH = "data/req_cache.json"
REVIEW_LOG_PATH = "data/req_review.log"
MODEL_NAME = "qwen2.5:14b"


def load_json_file(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read {filepath}: {e}")
    return {}


def save_json_file(data, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to write to {filepath}: {e}")


def clean_track_name(header_text):
    """'Economics Concentration' -> 'ECONOMICS'"""
    clean = re.sub(r'[^A-Za-z0-9\s]', '', header_text)
    clean = clean.replace("Concentration", "").strip().replace(" ", "_").upper()
    return clean


def make_cached_rule_parser(req_cache):
    """
    Returns a rule_parser_fn closure that caches LLM responses by text hash.
    Rule text like 'Five additional COMP courses 420 or higher' repeats across
    many degree pages so caching is high-value.
    """
    def parse_with_cache(text):
        key = hashlib.md5(text.encode('utf-8')).hexdigest()
        if key in req_cache:
            return req_cache[key]

        logger.info(f"  -> Cache miss, calling LLM on: {text[:80]}")
        parsed = parse_rule_text(text, model_name=MODEL_NAME)
        if parsed:
            req_cache[key] = parsed
            save_json_file(req_cache, req_cache_PATH)
        time.sleep(0.5)
        return parsed

    return parse_with_cache


def run_req_pipeline():
    logger.info("Starting Deterministic Requirements Pipeline...")

    if os.path.exists(REVIEW_LOG_PATH):
        os.remove(REVIEW_LOG_PATH)

    master_reqs = load_json_file(OUTPUT_PATH)
    req_cache = load_json_file(req_cache_PATH)
    rule_parser = make_cached_rule_parser(req_cache)

    for track_id, url in TARGET_TRACKS.items():
        logger.info(f"Processing {track_id}...")

        scraped = scrape_major_requirements(url)
        if not scraped:
            logger.warning(f"  No data scraped for {track_id}, skipping.")
            continue

        logger.info(f"  Found {len(scraped['sections'])} sections under header: '{scraped['main_header']}'")

        base_core = {"required_courses": [], "choice_groups": []}
        concentrations = []

        for section in scraped['sections']:
            block = assemble_section(section, rule_parser)
            b_type = block['block_type']

            logger.info(
                f"  [{b_type:13}] '{block['block_title']}' | "
                f"required: {len(block['required_courses'])} | "
                f"groups: {len(block['choice_groups'])}"
            )

            if b_type == 'reference_list':
                continue
            elif b_type == 'core':
                for code in block['required_courses']:
                    if code not in base_core['required_courses']:
                        base_core['required_courses'].append(code)
                base_core['choice_groups'].extend(block['choice_groups'])
            elif b_type == 'concentration':
                concentrations.append(block)

        master_reqs[track_id] = base_core
        logger.info(f"  Saved base track: {track_id} ({len(base_core['required_courses'])} required, "
                    f"{len(base_core['choice_groups'])} groups)")

        for conc in concentrations:
            suffix = clean_track_name(conc['block_title'])
            conc_track_id = f"{track_id}_{suffix}"
            merged_required = list(base_core['required_courses'])
            for code in conc['required_courses']:
                if code not in merged_required:
                    merged_required.append(code)
            master_reqs[conc_track_id] = {
                'required_courses': merged_required,
                'choice_groups': base_core['choice_groups'] + conc['choice_groups']
            }
            logger.info(f"  Saved concentration: {conc_track_id}")

    save_json_file(master_reqs, OUTPUT_PATH)
    logger.info(f"Pipeline complete. Saved {len(master_reqs)} tracks to {OUTPUT_PATH}")


if __name__ == "__main__":
    run_req_pipeline()