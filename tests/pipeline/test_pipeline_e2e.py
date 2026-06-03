"""
End-to-end test for the degree requirements pipeline.

Runs scrape -> assemble -> LLM-rule-parse for 6 programs, writes results to
data/staging/test_pipeline_output.json, then diffs every field against
data/degree_requirements.json (source of truth).

Tracks are chosen to cover distinct patterns WITHOUT reusing pages that were
debugged during assembler development (anti-overfitting):
  Data_Science_BS                       - 11 concentrations, no rule_based
  Environmental_Science_and_Studies_Minor - 1 rule_based ("Three additional ENEC courses at 400+")
  Physics_BS                            - 9 explicit groups, pure science
  Spanish_for_the_Professions_Minor     - 1 rule_based with exclusion list (SPAN 301+)
  Linguistics_Minor                     - 1 rule_based (LING 200+), humanities
  Mathematics_Minor                     - explicit groups only, simple baseline

Usage:
    python3 tests/test_pipeline_e2e.py [--model qwen2.5:14b]

Exit 0 = all structural checks passed, 1 = failures.

SAFETY: never writes to data/degree_requirements.json or data/.cache/req_cache.json.
"""

import sys
import os
import re
import json
import argparse
import hashlib
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scraper.requirements_scraper import scrape_major_requirements
from src.scraper.requirements_assembler import assemble_section
from src.scraper.llm_requirements_parser import parse_rule_text

# ── Config ─────────────────────────────────────────────────────────────────────

TRUTH_PATH  = "data/degree_requirements.json"
OUTPUT_PATH = "data/staging/test_pipeline_output.json"
COURSE_RE   = re.compile(r'^[A-Z]{2,5}\d{2,4}[A-Z]?$')

# Each entry: url, courses that must appear somewhere (required OR any group options),
# min expected choice_groups, whether concentrations are expected, and how many
# rule_based groups to expect (sanity floor — "at least N").
TEST_TRACKS = {
    "Data_Science_BS": {
        "url": "https://catalog.unc.edu/undergraduate/programs-study/data-science-major-bs/",
        "must_contain": ["DATA110", "DATA120"],
        "min_groups": 8,
        "expect_concentrations": True,   # 11 concentrations
        "min_rule_groups": 0,
    },
    "Environmental_Science_and_Studies_Minor": {
        "url": "https://catalog.unc.edu/undergraduate/programs-study/environmental-science-studies-minor/",
        "must_contain": ["ENEC201", "ENEC202"],
        "min_groups": 1,
        "expect_concentrations": False,
        "min_rule_groups": 1,   # "Three additional ENEC courses (at least one at 400+)" -> 1 rule_based
    },
    "Physics_BS": {
        "url": "https://catalog.unc.edu/undergraduate/programs-study/physics-major-bs/",
        "must_contain": ["PHYS331", "PHYS401", "PHYS521"],
        "min_groups": 5,
        "expect_concentrations": False,
        "min_rule_groups": 0,
    },
    "Spanish_for_the_Professions_Minor": {
        "url": "https://catalog.unc.edu/undergraduate/programs-study/spanish-professions-minor/",
        "must_contain": ["SPAN329"],
        "min_groups": 2,
        "expect_concentrations": False,
        "min_rule_groups": 1,   # SPAN 301+ (with exclusion list)
    },
    "Linguistics_Minor": {
        "url": "https://catalog.unc.edu/undergraduate/programs-study/linguistics-minor/",
        "must_contain": [],   # all requirements are rule_based
        "min_groups": 2,
        "expect_concentrations": False,
        "min_rule_groups": 1,   # LING 200+
    },
    "Mathematics_Minor": {
        "url": "https://catalog.unc.edu/undergraduate/programs-study/mathematics-minor/",
        "must_contain": ["MATH381", "MATH383"],
        "min_groups": 2,
        "expect_concentrations": False,
        "min_rule_groups": 0,
    },
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def valid_code(c):
    return bool(COURSE_RE.match(c))


def all_options_pool(track_data):
    pool = set()
    for g in track_data.get("base_requirements", {}).get("choice_groups", []):
        pool.update(g.get("options", []))
    for conc in track_data.get("concentrations", {}).values():
        for g in conc.get("choice_groups", []):
            pool.update(g.get("options", []))
    return pool


def rule_sig(rule_dict):
    if not rule_dict:
        return None
    return (
        rule_dict.get("department"),
        rule_dict.get("min_number"),
        rule_dict.get("min_credits"),
        frozenset(rule_dict.get("exclude") or []),
    )


class Checker:
    def __init__(self, track_id):
        self.track_id = track_id
        self.passed   = []
        self.failed   = []
        self.warnings = []

    def ok(self, label):
        self.passed.append(label)
        print(f"    [PASS] {label}")

    def fail(self, label, detail=""):
        self.failed.append(label)
        print(f"    [FAIL] {label}" + (f"\n           {detail}" if detail else ""))

    def warn(self, label, detail=""):
        self.warnings.append(label)
        print(f"    [WARN] {label}" + (f"\n           {detail}" if detail else ""))

    def summary(self):
        return (f"{len(self.passed)} passed, "
                f"{len(self.failed)} failed, "
                f"{len(self.warnings)} warnings")


# ── Pipeline runner ────────────────────────────────────────────────────────────

def make_rule_parser(model_name):
    cache = {}
    def _parse(text):
        key = hashlib.md5(text.encode()).hexdigest()
        if key not in cache:
            cache[key] = parse_rule_text(text, model_name=model_name)
            time.sleep(0.3)
        return cache[key]
    return _parse


def run_pipeline_for_track(url, rule_parser):
    scraped = scrape_major_requirements(url)
    if not scraped:
        return None

    base_core   = {"required_courses": [], "choice_groups": []}
    conc_blocks = []

    for section in scraped["sections"]:
        block  = assemble_section(section, rule_parser)
        b_type = block["block_type"]
        if b_type == "reference_list":
            continue
        elif b_type == "core":
            for code in block["required_courses"]:
                if code not in base_core["required_courses"]:
                    base_core["required_courses"].append(code)
            base_core["choice_groups"].extend(block["choice_groups"])
        elif b_type == "concentration":
            conc_blocks.append(block)

    seen = {}
    reindexed = []
    for g in base_core["choice_groups"]:
        base = re.sub(r'_\d+$', '', g['id'])
        seen[base] = seen.get(base, 0) + 1
        g = dict(g)
        g['id'] = f"{base}_{seen[base]}"
        if g.get('courses_required') and g.get('credits_required'):
            del g['credits_required']
        reindexed.append(g)
    base_core["choice_groups"] = reindexed

    concentrations = {"None": {"required_courses": [], "choice_groups": []}}
    for conc in conc_blocks:
        name = re.sub(r'[^A-Za-z0-9\s]', '', conc['block_title'])
        for kw in ('Concentration', 'Plan', 'Option', 'Track'):
            name = re.sub(rf'\b{kw}\b', '', name, flags=re.IGNORECASE)
        name = name.strip().replace(' ', '_') or 'None'
        concentrations[name] = {
            "required_courses": conc["required_courses"],
            "choice_groups":    conc["choice_groups"],
        }

    return {"base_requirements": base_core, "concentrations": concentrations}


# ── Structural checks ──────────────────────────────────────────────────────────

def check_structure(track_id, data, config, c: Checker):
    base   = data["base_requirements"]
    req    = base.get("required_courses", [])
    groups = base.get("choice_groups", [])

    c.ok("Scrape and assembly succeeded") if data else c.fail("Scrape/assembly returned None")

    # Required courses are a list of valid codes
    bad_req = [x for x in req if not valid_code(x)]
    if bad_req:
        c.fail("Invalid codes in required_courses", str(bad_req))
    else:
        c.ok(f"required_courses are all valid codes ({len(req)} courses)")

    # Choice groups minimum count
    if len(groups) >= config["min_groups"]:
        c.ok(f"choice_groups count {len(groups)} >= {config['min_groups']}")
    else:
        c.fail(f"choice_groups count too low", f"got {len(groups)}, expected >= {config['min_groups']}")

    # Group IDs unique
    ids = [g["id"] for g in groups]
    dups = [x for x in set(ids) if ids.count(x) > 1]
    if dups:
        c.fail("Duplicate choice group IDs", str(dups))
    else:
        c.ok("All choice group IDs are unique")

    # Group structure valid
    bad_groups = []
    for g in groups:
        errs = []
        if not g.get("id"):
            errs.append("missing id")
        if g.get("type") not in ("explicit", "rule_based"):
            errs.append(f"bad type {g.get('type')!r}")
        if not isinstance(g.get("courses_required"), int) or g["courses_required"] < 1:
            errs.append(f"bad courses_required {g.get('courses_required')!r}")
        if not isinstance(g.get("options"), list):
            errs.append("options not a list")
        else:
            bad_opts = [x for x in g["options"] if not valid_code(x)]
            if bad_opts:
                errs.append(f"bad option codes: {bad_opts}")
        if errs:
            bad_groups.append(f"{g.get('id')}: {errs}")
    if bad_groups:
        c.fail("Malformed choice groups", "; ".join(bad_groups[:3]))
    else:
        c.ok(f"All {len(groups)} choice groups are structurally valid")

    # rule_based group minimum
    rule_groups = [g for g in groups if g.get("type") == "rule_based"]
    if len(rule_groups) >= config["min_rule_groups"]:
        c.ok(f"rule_based group count {len(rule_groups)} >= {config['min_rule_groups']}")
        for g in rule_groups:
            rule = g.get("rule") or {}
            dept = rule.get("department")
            mn   = rule.get("min_number")
            mc   = rule.get("min_credits")
            excl = rule.get("exclude", [])
            print(f"      rule_based '{g['id']}': dept={dept} min_num={mn} min_credits={mc} "
                  f"courses_req={g['courses_required']} exclude={excl}")
    else:
        c.fail(
            f"Not enough rule_based groups",
            f"got {len(rule_groups)}, expected >= {config['min_rule_groups']} — "
            "LLM may have failed to parse the rule text",
        )

    # must_contain courses appear somewhere
    all_codes = set(req) | all_options_pool(data)
    for course in config["must_contain"]:
        if course in all_codes:
            c.ok(f"{course} present")
        else:
            c.fail(f"{course} missing from required_courses and all group options")

    # Concentrations
    concs = set(data.get("concentrations", {}).keys()) - {"None"}
    if config["expect_concentrations"]:
        if concs:
            c.ok(f"{len(concs)} concentration(s) found: {sorted(concs)}")
        else:
            c.fail("Expected concentrations but none found")
    else:
        if concs:
            print(f"    [INFO] {len(concs)} concentration(s) present (not required): {sorted(concs)}")


# ── Truth comparison ───────────────────────────────────────────────────────────

def compare_to_truth(track_id, data, truth_data, c: Checker):
    test_base  = data.get("base_requirements", {})
    truth_base = truth_data.get("base_requirements", {})

    test_req  = set(test_base.get("required_courses", []))
    truth_req = set(truth_base.get("required_courses", []))
    missing   = truth_req - test_req
    extra     = test_req  - truth_req
    if not missing and not extra:
        c.ok(f"required_courses exact match with truth ({len(truth_req)} courses)")
    else:
        # These are WARN not FAIL — known truth drift (MATH231/232 wrapping, page changes)
        if missing:
            c.warn(f"Courses in truth required but not in test required", str(sorted(missing)))
        if extra:
            c.warn(f"Courses in test required but not in truth required", str(sorted(extra)))

    test_ng  = len(test_base.get("choice_groups", []))
    truth_ng = len(truth_base.get("choice_groups", []))
    if test_ng == truth_ng:
        c.ok(f"choice_groups count matches truth ({truth_ng})")
    else:
        c.warn(f"choice_groups count differs from truth", f"truth={truth_ng}  test={test_ng}")

    # Rule group signatures
    truth_rules = {rule_sig(g.get("rule")): g
                   for g in truth_base.get("choice_groups", []) if g.get("type") == "rule_based"}
    test_rules  = {rule_sig(g.get("rule")): g
                   for g in test_base.get("choice_groups", [])  if g.get("type") == "rule_based"}
    for sig, tg in truth_rules.items():
        if sig in test_rules:
            c.ok(f"Rule group reproduced: dept={sig[0]} min_num={sig[1]}")
        else:
            # Partial match: same dept+min_num but different exclusions?
            partial = next(
                (s for s in test_rules if s and s[0] == sig[0] and s[1] == sig[1]), None
            )
            if partial:
                missing_excl = sig[3] - partial[3]
                extra_excl   = partial[3] - sig[3]
                c.warn(
                    f"Rule group dept={sig[0]} min_num={sig[1]} matched but exclusions differ",
                    (f"truth_excl={sorted(sig[3])}  test_excl={sorted(partial[3])}"
                     + (f"  missing={sorted(missing_excl)}" if missing_excl else "")
                     + (f"  extra={sorted(extra_excl)}" if extra_excl else "")),
                )
            else:
                c.warn(f"Rule group from truth not found in test",
                       f"dept={sig[0]} min_num={sig[1]} min_credits={sig[2]}")

    # Options pool diff
    test_pool  = all_options_pool(data)
    truth_pool = all_options_pool(truth_data)
    missing_opts = truth_pool - test_pool
    extra_opts   = test_pool  - truth_pool
    if not missing_opts and not extra_opts:
        c.ok(f"Options pool exact match ({len(truth_pool)} courses)")
    else:
        if missing_opts:
            c.warn(f"{len(missing_opts)} course(s) in truth pool but not in test",
                   str(sorted(missing_opts)))
        if extra_opts:
            c.warn(f"{len(extra_opts)} course(s) in test pool but not in truth",
                   str(sorted(extra_opts)))

    # Concentration names
    test_concs  = set(data.get("concentrations", {}).keys())
    truth_concs = set(truth_data.get("concentrations", {}).keys())
    missing_concs = truth_concs - test_concs
    if not missing_concs:
        c.ok(f"All {len(truth_concs)} concentration name(s) present")
    else:
        c.warn(f"Concentration names from truth missing in test", str(sorted(missing_concs)))
    extra_concs = test_concs - truth_concs
    if extra_concs:
        c.warn("New concentrations not in truth (page may have been renamed)",
               str(sorted(extra_concs)))


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen2.5:14b",
                        help="Ollama model for rule parsing (default: qwen2.5:14b)")
    args = parser.parse_args()

    print(f"Model  : {args.model}")
    print(f"Truth  : {TRUTH_PATH}")
    print(f"Output : {OUTPUT_PATH}")
    print(f"Tracks : {list(TEST_TRACKS)}\n")

    if not os.path.exists(TRUTH_PATH):
        print(f"ERROR: {TRUTH_PATH} not found"); sys.exit(1)
    with open(TRUTH_PATH) as f:
        truth = json.load(f)

    rule_parser  = make_rule_parser(args.model)
    test_results = {}
    all_checkers = []

    for track_id, config in TEST_TRACKS.items():
        print(f"\n{'─' * 60}")
        print(f"  {track_id}")
        print(f"{'─' * 60}")

        print("  [1/3] Scraping + assembling ...")
        data = run_pipeline_for_track(config["url"], rule_parser)

        c = Checker(track_id)
        all_checkers.append(c)

        if data is None:
            c.fail("Scrape/assemble failed — no sc_courselist tables found")
            continue

        base  = data["base_requirements"]
        nreq  = len(base["required_courses"])
        ngrp  = len(base["choice_groups"])
        nrule = sum(1 for g in base["choice_groups"] if g.get("type") == "rule_based")
        nconc = len(data["concentrations"]) - 1
        print(f"  [2/3] Assembled: {nreq} required, {ngrp} groups "
              f"({nrule} rule_based), {nconc} concentration(s)")
        test_results[track_id] = data

        print(f"  [3/3] Structural checks ...")
        check_structure(track_id, data, config, c)

        if track_id in truth:
            print(f"  [4/4] Comparing against source of truth ...")
            compare_to_truth(track_id, data, truth[track_id], c)
        else:
            c.warn(f"Track not in {TRUTH_PATH} — skipping diff")

        print(f"  => {c.summary()}")

    # Write output (never touches truth file)
    os.makedirs("data", exist_ok=True)
    tmp = OUTPUT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(test_results, f, indent=2)
    os.replace(tmp, OUTPUT_PATH)
    print(f"\nTest output written to {OUTPUT_PATH}")

    total_passed  = sum(len(c.passed)   for c in all_checkers)
    total_failed  = sum(len(c.failed)   for c in all_checkers)
    total_warnings = sum(len(c.warnings) for c in all_checkers)

    print(f"\n{'=' * 60}")
    print(f"FINAL: {total_passed} passed  |  {total_failed} failed  |  {total_warnings} warnings")
    print("(WARN = differs from truth; may be page drift or known Gemini enrichment diff)")

    if total_failed > 0:
        print("RESULT: FAIL")
        for c in all_checkers:
            if c.failed:
                print(f"  {c.track_id}: {c.failed}")
        sys.exit(1)
    else:
        print("RESULT: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
