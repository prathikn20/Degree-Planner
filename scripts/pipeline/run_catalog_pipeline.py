import json
import logging
import time
import re
import os
import sys
import hashlib
import itertools
import random

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
    "https://catalog.unc.edu/courses/busi/",
    "https://catalog.unc.edu/courses/econ/",
    "https://catalog.unc.edu/courses/psyc/",
    "https://catalog.unc.edu/courses/biol/",
    "https://catalog.unc.edu/courses/chem/",
    "https://catalog.unc.edu/courses/phys/",
    "https://catalog.unc.edu/courses/nsci/",
    "https://catalog.unc.edu/courses/exss/",

    "https://catalog.unc.edu/courses/mejo/",
    "https://catalog.unc.edu/courses/poli/",
    "https://catalog.unc.edu/courses/hist/",
    "https://catalog.unc.edu/courses/engl/",
    "https://catalog.unc.edu/courses/comm/",
    "https://catalog.unc.edu/courses/soci/",
    "https://catalog.unc.edu/courses/pwad/",
    "https://catalog.unc.edu/courses/anth/",
    "https://catalog.unc.edu/courses/phil/",
    "https://catalog.unc.edu/courses/plcy/",
    "https://catalog.unc.edu/courses/educ/",
    "https://catalog.unc.edu/courses/glbl/",
    "https://catalog.unc.edu/courses/wgst/",

    "https://catalog.unc.edu/courses/enec/",
    "https://catalog.unc.edu/courses/envr/",
    "https://catalog.unc.edu/courses/emes/",
    "https://catalog.unc.edu/courses/geog/",
    "https://catalog.unc.edu/courses/appl/",
    "https://catalog.unc.edu/courses/mngt/",
    "https://catalog.unc.edu/courses/plan/",
    "https://catalog.unc.edu/courses/inls/",
    "https://catalog.unc.edu/courses/scll/",
    "https://catalog.unc.edu/courses/amst/",
    "https://catalog.unc.edu/courses/aaad/",
    "https://catalog.unc.edu/courses/ltam/",
    "https://catalog.unc.edu/courses/euro/",
    "https://catalog.unc.edu/courses/jwst/",

    "https://catalog.unc.edu/courses/arts/",
    "https://catalog.unc.edu/courses/arth/",
    "https://catalog.unc.edu/courses/dram/",
    "https://catalog.unc.edu/courses/musc/",
    "https://catalog.unc.edu/courses/cmpl/",
    "https://catalog.unc.edu/courses/folk/",
    "https://catalog.unc.edu/courses/reli/",

    "https://catalog.unc.edu/courses/lfit/",
    "https://catalog.unc.edu/courses/phya/",
    "https://catalog.unc.edu/courses/ures/",
    "https://catalog.unc.edu/courses/idst/",
    "https://catalog.unc.edu/courses/spcl/",
    "https://catalog.unc.edu/courses/aero/",
    "https://catalog.unc.edu/courses/army/",
    "https://catalog.unc.edu/courses/navs/",

    "https://catalog.unc.edu/courses/sphg/",
    "https://catalog.unc.edu/courses/hpm/",
    "https://catalog.unc.edu/courses/epid/",
    "https://catalog.unc.edu/courses/bios/",
    "https://catalog.unc.edu/courses/nutr/",
    "https://catalog.unc.edu/courses/nurs/",
    "https://catalog.unc.edu/courses/hbeh/",   # Health Behavior — needed by CGPH BSPH
    "https://catalog.unc.edu/courses/chip/",   # Carolina Health Informatics — needed by DS BS Health Informatics
    "https://catalog.unc.edu/courses/phrs/",   # Pharmaceutical Sciences — needed by Pharm Sci Minor
    "https://catalog.unc.edu/courses/bmme/",
    "https://catalog.unc.edu/courses/mcro/",
    "https://catalog.unc.edu/courses/icmu/",
    "https://catalog.unc.edu/courses/sphs/",
    "https://catalog.unc.edu/courses/clsc/",
    "https://catalog.unc.edu/courses/radi/",
    "https://catalog.unc.edu/courses/dhyg/",
    "https://catalog.unc.edu/courses/ndss/",

    "https://catalog.unc.edu/courses/ling/",
    "https://catalog.unc.edu/courses/span/",
    "https://catalog.unc.edu/courses/fren/",
    "https://catalog.unc.edu/courses/chin/",
    "https://catalog.unc.edu/courses/japn/",
    "https://catalog.unc.edu/courses/kor/",
    "https://catalog.unc.edu/courses/germ/",
    "https://catalog.unc.edu/courses/ital/",
    "https://catalog.unc.edu/courses/latn/",
    "https://catalog.unc.edu/courses/grek/",
    "https://catalog.unc.edu/courses/arab/",
    "https://catalog.unc.edu/courses/russ/",
    "https://catalog.unc.edu/courses/hnur/",
    "https://catalog.unc.edu/courses/hebr/",
    "https://catalog.unc.edu/courses/prsn/",
    "https://catalog.unc.edu/courses/port/",
    "https://catalog.unc.edu/courses/viet/",
    "https://catalog.unc.edu/courses/swah/",
    "https://catalog.unc.edu/courses/yoru/",
    "https://catalog.unc.edu/courses/wolo/",
    "https://catalog.unc.edu/courses/lgla/",
    "https://catalog.unc.edu/courses/cher/",
    "https://catalog.unc.edu/courses/chwa/",
    "https://catalog.unc.edu/courses/cata/",
    "https://catalog.unc.edu/courses/dtch/",
    "https://catalog.unc.edu/courses/czch/",
    "https://catalog.unc.edu/courses/bcs/",
    "https://catalog.unc.edu/courses/plsh/",
    "https://catalog.unc.edu/courses/hung/",
    "https://catalog.unc.edu/courses/turk/",
    "https://catalog.unc.edu/courses/ukrn/",
    "https://catalog.unc.edu/courses/macd/",
    "https://catalog.unc.edu/courses/asia/",
    "https://catalog.unc.edu/courses/clas/",
    "https://catalog.unc.edu/courses/arch/",
    "https://catalog.unc.edu/courses/clar/",
    "https://catalog.unc.edu/courses/gsll/",
    "https://catalog.unc.edu/courses/roml/",
    "https://catalog.unc.edu/courses/slav/"
]
OUTPUT_PATH = "data/course_catalog.json"
CACHE_PATH = "data/.cache/course_cache.json"
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

                    time.sleep(2.5)

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

    # Post-processing: ensure all I-suffix and IDST courses carry the INTERDISCIPLINARY
    # attribute.  The catalog page itself is the authoritative marker — no Gen Ed tag is
    # printed in the course block — so we derive the attribute from the course code here.
    for cid, cdata in normalized_catalog.items():
        is_idst = cid.startswith('IDST')
        is_i_suffix = len(cid) > 1 and cid[-1] == 'I' and cid[-2].isdigit()
        if is_idst or is_i_suffix:
            attrs = cdata.setdefault('attributes', [])
            if 'INTERDISCIPLINARY' not in attrs:
                attrs.append('INTERDISCIPLINARY')

    # Ensure courses listed on the IDST website that may not have a dedicated
    # catalog page (GEOG117H, WGST111H, etc.) are present with the attribute.
    _IDST_WEBSITE_COURSES = {
        'AMST101I', 'AMST217I', 'ANTH210I', 'ASIA125I', 'ASIA426I', 'ASIA447I',
        'DATA420I', 'ECON573I', 'EDUC321I', 'ENEC202I', 'ENGL217I', 'EXSS321I',
        'GEOG117I', 'GEOG117H', 'GEOG210I', 'GEOG447I', 'GERM416I', 'GLBL210I',
        'GSLL275I', 'HIST210I', 'HIST217I', 'ITAL325I', 'JWST100I', 'LING545I',
        'LTAM117I', 'LTAM117H', 'MHCH150I', 'MUSC51I', 'PHYS51I', 'PHYS150I',
        'POLI210I', 'PORT270I', 'RELI123I', 'STOR323I', 'WGST111I', 'WGST111H',
        'WGST117I', 'WGST117H', 'WGST262I', 'WGST447I',
    }
    _H_CROSS = {
        'GEOG117H': 'GEOG117I', 'LTAM117H': 'LTAM117I',
        'WGST111H': 'WGST111I', 'WGST117H': 'WGST117I',
    }
    for cid in _IDST_WEBSITE_COURSES:
        if cid not in normalized_catalog:
            normalized_catalog[cid] = {
                'name': f'Interdisciplinary Perspectives ({cid})',
                'credits': 3.0,
                'prerequisites': [],
                'corequisites': [],
                'cross_listed': [_H_CROSS[cid]] if cid in _H_CROSS else [],
                'attributes': ['INTERDISCIPLINARY'],
            }
        else:
            attrs = normalized_catalog[cid].setdefault('attributes', [])
            if 'INTERDISCIPLINARY' not in attrs:
                attrs.append('INTERDISCIPLINARY')

    # Post-processing: strip any cross_listed code that does not exist as a catalog key.
    # This prevents stale "Previously offered as" codes (renumbered courses) from polluting
    # the cross_listed arrays and breaking path validation in requirements_checker.py.
    valid_keys = set(normalized_catalog.keys())
    for cid, cdata in normalized_catalog.items():
        raw_cross = cdata.get("cross_listed", [])
        clean_cross = [c for c in raw_cross if c in valid_keys]
        if len(clean_cross) != len(raw_cross):
            removed = [c for c in raw_cross if c not in valid_keys]
            logger.debug(f"Removed stale cross_listed codes from {cid}: {removed}")
            cdata["cross_listed"] = clean_cross

    save_catalog(normalized_catalog)
    logger.info("Final catalog saved.")

    # ── Post-pipeline data quality report ────────────────────────────────────
    valid_keys = set(normalized_catalog.keys())

    # Ghost prerequisite summary (courses whose prereqs reference non-existent courses)
    ghost_prereq_counts: dict[str, int] = {}
    for cid, cdata in normalized_catalog.items():
        for pathway in (cdata.get("prerequisites") or []):
            for prereq in pathway:
                if prereq not in valid_keys:
                    ghost_prereq_counts[prereq] = ghost_prereq_counts.get(prereq, 0) + 1
    if ghost_prereq_counts:
        top = sorted(ghost_prereq_counts.items(), key=lambda x: -x[1])[:10]
        logger.warning(
            "Ghost prerequisite references (not in catalog): %d unique codes. "
            "Top offenders: %s. Add their department URLs to TARGET_URLS if they exist.",
            len(ghost_prereq_counts), top
        )
    else:
        logger.info("No ghost prerequisite references — all prereq codes exist in catalog.")

    # Zero-credit course summary
    zero_cr = [c for c, d in normalized_catalog.items() if d.get("credits", 1) == 0]
    if zero_cr:
        logger.warning("Zero-credit courses: %d  Sample: %s", len(zero_cr), zero_cr[:5])

    logger.info(f"Pipeline complete! Saved to {OUTPUT_PATH}")
    logger.info("Run 'python scripts/validate_pipeline_output.py' for a full data quality audit.")
    if os.path.exists(LOG_PATH):
        logger.warning(f"WARNING: Some courses were flagged. Check {LOG_PATH} for details.")
    else:
        logger.info(f"SUCCESS: Clean run. No structural anomalies detected.")

if __name__ == "__main__":
    run_ingestion_pipeline()