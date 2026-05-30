import argparse
import json
import logging
import os
import sys
import time
import hashlib
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scraper.req_scraper import scrape_major_requirements
from src.scraper.req_assembler import assemble_section
from src.scraper.llm_req_parser import parse_rule_text

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_MODEL   = "qwen2.5:32b"
OUTPUT_PATH     = "data/test_degree_requirements.json"
CACHE_PATH      = "data/req_cache.json"

# Every program that appears in the live degree_requirements.json, keyed by the
# track_id the app uses.  UNC_General_Education is attribute-rule-based and not
# scrapeable from a sc_courselist page, so it is intentionally excluded here —
# keep maintaining it manually in the production file.
TARGET_TRACKS = {
    # ── Majors ────────────────────────────────────────────────────────────────
    "Computer_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/computer-science-major-bs/",
    "Data_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/data-science-major-bs/",
    "Mathematics_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/mathematics-major-bs/",
    "Statistics_and_Analytics_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/statistics-analytics-major-bs/",
    "Economics_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/economics-major-bs/",
    "Biology_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/biology-major-bs/",
    "Chemistry_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/chemistry-major-bs/",
    "Physics_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/physics-major-bs/",
    "Neuroscience_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/neuroscience-major-bs/",
    "Psychology_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/psychology-major-bs/",
    "Political_Science_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/political-science-major-ba/",
    "Public_Policy_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/public-policy-major-ba/",
    "Exercise_and_Sport_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-bs/",
    "Biomedical_Engineering_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/biomedical-engineering-major-bs/",
    "Biostatistics_BSPH":
        "https://catalog.unc.edu/undergraduate/programs-study/biostatistics-bsph/",
    "Business_Administration_BSBA":
        "https://catalog.unc.edu/undergraduate/programs-study/business-administration-bsba/",
    # ── Minors ────────────────────────────────────────────────────────────────
    "Computer_Science_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/computer-science-minor/",
    "Data_Science_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/data-science-minor/",
    "Mathematics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/mathematics-minor/",
    "Economics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/economics-minor/",
    "Biology_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/biology-minor/",
    "Chemistry_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/chemistry-minor/",
    "Physics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/physics-minor/",
    "Business_Administration_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/business-administration-minor/",
    "Philosophy_Politics_and_Economics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/philosophy-politics-economics-minor/",
    "Public_Policy_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/public-policy-minor/",
    "Entrepreneurship_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/entrepreneurship-minor/",
    "Philosophy_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/philosophy-minor/",
    "Linguistics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/linguistics-minor/",
    "Environmental_Science_and_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/environmental-science-studies-minor/",
    "Applied_Sciences_and_Engineering_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/applied-sciences-engineering-minor/",
    "Anthropology_General_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/anthropology-general-minor/",
    "Medical_Anthropology_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/medical-anthropology-minor/",
    "Marine_Sciences_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/marine-sciences-minor/",
    "Spanish_for_the_Professions_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/spanish-professions-minor/",
    "Sociology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/sociology-major-ba/",
}


def load_json_file(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read {filepath}: {e}")
    return {}


def save_json_file(data, filepath):
    """Atomic write: write to .tmp then rename — same pattern as catalog pipeline."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        tmp_path = filepath + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, filepath)
    except Exception as e:
        logger.error(f"Failed to write to {filepath}: {e}")


def clean_conc_name(header_text: str) -> str:
    """
    'Economics Concentration' → 'Economics'
    'Machine Learning and AI Concentration' → 'Machine_Learning_and_AI'
    Preserves Title Case so IDs are readable.
    """
    text = re.sub(r'[^A-Za-z0-9\s]', '', header_text)
    for kw in ('Concentration', 'Plan', 'Option', 'Track'):
        text = re.sub(rf'\b{kw}\b', '', text, flags=re.IGNORECASE)
    text = text.strip()
    return text.replace(' ', '_') if text else 'None'


def reindex_choice_groups(groups: list) -> list:
    """
    Give every choice group in a merged list a unique, sequential ID.

    assemble_section() uses a per-section counter, so two sections both start
    at choice_1 / list_1 / rule_1.  When their groups are concatenated into one
    base_requirements list the duplicates would silently mask each other in the
    requirements checker (which keys satisfied/unsatisfied by group id).

    Also drops `credits_required` from groups that already have a meaningful
    `courses_required` — the assembler can set both when the list-header row has
    an hours column, but the requirements checker treats credits_required as
    authoritative and would ignore courses_required.
    """
    seen: dict[str, int] = {}
    result = []
    for g in groups:
        base = re.sub(r'_\d+$', '', g['id'])         # strip existing suffix
        seen[base] = seen.get(base, 0) + 1
        g = dict(g)                                    # shallow copy — don't mutate original
        g['id'] = f"{base}_{seen[base]}"

        # If both counts are present, keep only courses_required (count-based wins)
        if g.get('courses_required') and g.get('credits_required'):
            del g['credits_required']

        result.append(g)
    return result


def make_cached_rule_parser(req_cache: dict, model_name: str):
    """
    Returns a caching wrapper around parse_rule_text.
    Rule text like 'Five additional COMP courses 420 or higher' repeats across
    many degree pages — caching avoids redundant LLM calls.
    Same hash + atomic-save pattern as the catalog pipeline's course_cache.
    """
    def parse_with_cache(text: str):
        key = hashlib.md5(text.encode('utf-8')).hexdigest()
        if key in req_cache:
            return req_cache[key]

        logger.info(f"  -> Cache miss, calling LLM: {text[:80]}")
        parsed = parse_rule_text(text, model_name=model_name)
        if parsed:
            req_cache[key] = parsed
            save_json_file(req_cache, CACHE_PATH)  # flush immediately — never lose work
        time.sleep(0.5)
        return parsed

    return parse_with_cache


def run_req_pipeline(model_name: str, force: bool = False):
    logger.info("Starting Requirements Pipeline  model=%s  output=%s", model_name, OUTPUT_PATH)

    # Seed with existing output so a partial re-run doesn't wipe already-done tracks.
    master_reqs = load_json_file(OUTPUT_PATH)
    req_cache   = load_json_file(CACHE_PATH)
    rule_parser = make_cached_rule_parser(req_cache, model_name)

    for track_id, url in TARGET_TRACKS.items():
        if not force and track_id in master_reqs:
            logger.info("Skipping %s (already in output — use --force to reprocess)", track_id)
            continue

        logger.info("Processing %s ...", track_id)

        scraped = scrape_major_requirements(url)
        if not scraped:
            logger.warning("  No sc_courselist tables found — skipping %s", track_id)
            continue

        logger.info("  %d sections under header: '%s'", len(scraped['sections']), scraped['main_header'])

        base_core   = {"required_courses": [], "choice_groups": []}
        conc_blocks = []

        for section in scraped['sections']:
            block  = assemble_section(section, rule_parser)
            b_type = block['block_type']

            logger.info(
                "  [%-13s] '%s' | req: %d | groups: %d",
                b_type, block['block_title'],
                len(block['required_courses']), len(block['choice_groups']),
            )

            if b_type == 'reference_list':
                continue
            elif b_type == 'core':
                seen = set(base_core['required_courses'])
                for code in block['required_courses']:
                    if code not in seen:
                        base_core['required_courses'].append(code)
                        seen.add(code)
                base_core['choice_groups'].extend(block['choice_groups'])
            elif b_type == 'concentration':
                conc_blocks.append(block)

        # Build the nested structure the app's requirements_checker expects:
        #   base_requirements holds the shared core.
        #   concentrations holds ONLY concentration-specific additions.
        #   The checker merges them at runtime — don't pre-merge here.
        #
        # reindex_choice_groups() fixes duplicate IDs that arise when groups
        # from multiple sections are merged, and drops credits_required on
        # groups that already have a meaningful courses_required.
        base_core['choice_groups'] = reindex_choice_groups(base_core['choice_groups'])

        concentrations: dict = {"None": {"required_courses": [], "choice_groups": []}}
        for conc in conc_blocks:
            name = clean_conc_name(conc['block_title'])
            if name in concentrations:
                logger.warning("  Duplicate concentration name '%s' in %s — merging", name, track_id)
                concentrations[name]['required_courses'].extend(conc['required_courses'])
                concentrations[name]['choice_groups'].extend(conc['choice_groups'])
            else:
                concentrations[name] = {
                    "required_courses": conc['required_courses'],
                    "choice_groups":    reindex_choice_groups(conc['choice_groups']),
                }

        master_reqs[track_id] = {
            "base_requirements": base_core,
            "concentrations":    concentrations,
        }

        # Checkpoint after every track — same philosophy as catalog pipeline
        # flushing after every LLM call: never lose completed work to a crash.
        save_json_file(master_reqs, OUTPUT_PATH)
        logger.info(
            "  Saved %s  (%d req, %d groups, %d concentration(s))",
            track_id,
            len(base_core['required_courses']),
            len(base_core['choice_groups']),
            len(concentrations) - 1,  # exclude the implicit 'None'
        )

    save_json_file(master_reqs, OUTPUT_PATH)
    logger.info("Pipeline complete. %d tracks written to %s", len(master_reqs), OUTPUT_PATH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Build degree requirements JSON from UNC catalog')
    parser.add_argument('--model', default=DEFAULT_MODEL,
                        help=f'Ollama model name (default: {DEFAULT_MODEL})')
    parser.add_argument('--force', action='store_true',
                        help='Reprocess tracks already present in the output file')
    args = parser.parse_args()
    run_req_pipeline(model_name=args.model, force=args.force)
