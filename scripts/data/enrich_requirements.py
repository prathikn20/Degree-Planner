"""
Post-processing enrichment pass over degree_requirements.json.

Runs after run_requirements_pipeline.py.  No LLM needed — pure logic.

What it does
------------
For every rule_based choice group, find courses already listed as
required in that track (base + concentration) that would satisfy the
rule's own filter (same department, number >= min_number, credits >=
min_credits).  Add those courses to the group's exclude list so they
can't be double-counted toward the elective requirement.

Example: CS BS has COMP455 and COMP550 as required courses.  The
rule_based group says "5 COMP courses >= 420".  Both required courses
match that filter, so they get added to exclude — otherwise a student
who took COMP455 might think it also counts as one of their five
electives.

Usage
-----
    python3 scripts/enrich_requirements.py
    python3 scripts/enrich_requirements.py --input data/staging/test_pipeline_output.json
                                            --output data/degree_requirements.json
"""

import argparse
import json
import logging
import os
import re
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

COURSE_NUM_RE = re.compile(r'\d+')


def course_number(code: str) -> int | None:
    m = COURSE_NUM_RE.search(code)
    return int(m.group()) if m else None


def matches_rule(code: str, rule: dict, catalog: dict) -> bool:
    """Return True if course `code` satisfies rule's filter criteria."""
    dept     = rule.get('department')
    min_num  = rule.get('min_number')
    min_cred = rule.get('min_credits')

    if dept and not code.startswith(dept):
        return False

    if min_num is not None:
        num = course_number(code)
        if num is None or num < min_num:
            return False

    if min_cred is not None:
        credits = catalog.get(code, {}).get('credits', 0)
        if (credits or 0) < min_cred:
            return False

    return True


def enrich_groups(groups: list, required_pool: set, catalog: dict, track_id: str) -> int:
    """Mutates groups in place. Returns count of exclusions added."""
    added = 0
    for group in groups:
        if group.get('type') != 'rule_based':
            continue
        rule = group.get('rule')
        if not rule:
            continue

        current_exclude = set(rule.get('exclude') or [])
        newly_added = []

        for code in sorted(required_pool):
            if code in current_exclude:
                continue
            if matches_rule(code, rule, catalog):
                current_exclude.add(code)
                newly_added.append(code)

        if newly_added:
            rule['exclude'] = sorted(current_exclude)
            added += len(newly_added)
            logger.info(
                '  [%s] group %s — added to exclude: %s',
                track_id, group['id'], newly_added
            )

    return added


def enrich_track(track_id: str, track_data: dict, catalog: dict) -> int:
    """Enrich all rule_based groups in one track. Returns total exclusions added."""
    base = track_data.get('base_requirements', {})
    base_required = set(base.get('required_courses', []))

    total = 0

    # Enrich base choice groups using base required courses
    total += enrich_groups(
        base.get('choice_groups', []),
        base_required,
        catalog,
        track_id,
    )

    # Enrich each concentration's choice groups using base + concentration required courses
    for conc_name, conc_data in track_data.get('concentrations', {}).items():
        if conc_name == 'None':
            continue
        conc_required = base_required | set(conc_data.get('required_courses', []))
        added = enrich_groups(
            conc_data.get('choice_groups', []),
            conc_required,
            catalog,
            f'{track_id}/{conc_name}',
        )
        total += added

    return total


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json(data: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description='Enrich degree requirements with auto-exclusions')
    parser.add_argument(
        '--input', default='data/degree_requirements.json',
        help='Requirements file to enrich (default: data/degree_requirements.json)',
    )
    parser.add_argument(
        '--output', default=None,
        help='Output path (default: overwrite --input in-place)',
    )
    parser.add_argument(
        '--catalog', default='data/course_catalog.json',
        help='Course catalog for credit-hour lookups (default: data/course_catalog.json)',
    )
    args = parser.parse_args()

    output_path = args.output or args.input

    logger.info('Input  : %s', args.input)
    logger.info('Output : %s', output_path)
    logger.info('Catalog: %s', args.catalog)

    requirements = load_json(args.input)
    catalog = load_json(args.catalog) if os.path.exists(args.catalog) else {}
    if not catalog:
        logger.warning('Catalog not found — credit-hour filter will be skipped')

    total_added = 0
    for track_id, track_data in requirements.items():
        added = enrich_track(track_id, track_data, catalog)
        total_added += added

    save_json(requirements, output_path)
    logger.info('Done. %d exclusion(s) added across all tracks → %s', total_added, output_path)


if __name__ == '__main__':
    main()
