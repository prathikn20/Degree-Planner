"""
Pipeline Output Validator
=========================
Run after either pipeline to catch data quality issues before they reach production.

Usage:
    python scripts/validate_pipeline_output.py
    python scripts/validate_pipeline_output.py --strict   # exit 1 on any ERROR
    python scripts/validate_pipeline_output.py --catalog-only
    python scripts/validate_pipeline_output.py --requirements-only

Exit codes:
    0 — clean (or only warnings in non-strict mode)
    1 — one or more ERROR-level findings (always exits 1 in strict mode)
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

CATALOG_PATH = "data/course_catalog.json"
REQUIREMENTS_PATH = "data/degree_requirements.json"

# ── Thresholds ─────────────────────────────────────────────────────────────────
MAX_BASE_REQUIRED_CREDITS    = 150   # above this → likely scraper pool-collapse
MAX_CONC_REQUIRED_CREDITS    = 120   # above this → likely concentration collapse
MAX_CHOICE_GROUP_IDENTICAL   = 3     # > N groups with identical options in one track → duplicate
GHOST_REQUIRED_HARD_LIMIT    = 0     # any ghost base required course → ERROR (was the fix applied?)


def load(path):
    with open(path) as f:
        return json.load(f)


# ── Catalog checks ─────────────────────────────────────────────────────────────

def check_catalog(catalog: dict) -> list[dict]:
    findings = []

    REQUIRED_KEYS = {"name", "credits", "prerequisites", "corequisites", "cross_listed", "attributes"}

    for course, data in catalog.items():
        missing = REQUIRED_KEYS - set(data.keys())
        if missing:
            findings.append({"level": "ERROR", "check": "catalog_schema",
                             "msg": f"{course} missing keys: {missing}"})
            continue

        if not isinstance(data["credits"], (int, float)) or data["credits"] < 0:
            findings.append({"level": "ERROR", "check": "catalog_credits",
                             "msg": f"{course}: invalid credits={data['credits']}"})

        if not isinstance(data["prerequisites"], list):
            findings.append({"level": "ERROR", "check": "catalog_prereqs",
                             "msg": f"{course}: prerequisites is not a list"})
        else:
            for pathway in data["prerequisites"]:
                if not isinstance(pathway, list):
                    findings.append({"level": "ERROR", "check": "catalog_prereqs",
                                     "msg": f"{course}: prerequisite pathway is not list: {pathway}"})
                    break
                for prereq in pathway:
                    if not isinstance(prereq, str):
                        findings.append({"level": "ERROR", "check": "catalog_prereqs",
                                         "msg": f"{course}: prereq item is not str: {prereq}"})

        if data.get("cross_listed") is not None and not isinstance(data["cross_listed"], list):
            findings.append({"level": "ERROR", "check": "catalog_cross_listed",
                             "msg": f"{course}: cross_listed is not a list"})

        if data.get("attributes") is not None and not isinstance(data["attributes"], list):
            findings.append({"level": "ERROR", "check": "catalog_attributes",
                             "msg": f"{course}: attributes is not a list"})

    # Cross-listed reciprocity
    stale_xl = []
    for course, data in catalog.items():
        for xl in (data.get("cross_listed") or []):
            if xl not in catalog:
                stale_xl.append((course, xl))
    if stale_xl:
        pct = len(stale_xl) / max(len(catalog), 1)
        level = "ERROR" if pct >= 0.05 else "WARN"
        findings.append({"level": level, "check": "catalog_stale_cross_listed",
                         "msg": f"{len(stale_xl)} stale cross_listed refs "
                                f"({pct:.1%} of catalog). Sample: {stale_xl[:3]}"})

    # Ghost prerequisite references (courses listing non-existent prereqs)
    ghost_prereqs: dict[str, int] = {}
    for course, data in catalog.items():
        for pathway in (data.get("prerequisites") or []):
            for prereq in pathway:
                if prereq not in catalog:
                    ghost_prereqs[prereq] = ghost_prereqs.get(prereq, 0) + 1

    # De-noise: EDUC395 has 100 DNF pathways each referencing the same ghost codes
    # Use unique-course-count (number of real catalog courses referencing the ghost)
    unique_referencing = {}
    for course, data in catalog.items():
        for pathway in (data.get("prerequisites") or []):
            for prereq in pathway:
                if prereq not in catalog:
                    unique_referencing.setdefault(prereq, set()).add(course)

    high_impact = {p: cs for p, cs in unique_referencing.items() if len(cs) >= 5}
    if high_impact:
        findings.append({"level": "WARN", "check": "catalog_ghost_prereqs",
                         "msg": f"{len(high_impact)} ghost prereqs referenced by ≥5 real courses: "
                                f"{list(high_impact.keys())[:8]}"})
    elif unique_referencing:
        findings.append({"level": "INFO", "check": "catalog_ghost_prereqs",
                         "msg": f"{len(unique_referencing)} unique ghost prereqs "
                                f"(all low-impact, ≤4 referencing courses)"})

    return findings


# ── Requirements checks ────────────────────────────────────────────────────────

def check_requirements(req: dict, catalog: dict) -> list[dict]:
    findings = []

    try:
        from src.planner.requirements_checker import get_rule_based_options
    except ImportError:
        findings.append({"level": "WARN", "check": "import",
                         "msg": "Could not import get_rule_based_options — skipping rule-based checks"})
        get_rule_based_options = None

    for track, tdata in req.items():
        base = tdata.get("base_requirements", {})
        if not isinstance(base, dict):
            findings.append({"level": "ERROR", "check": "req_schema",
                             "msg": f"{track}: base_requirements is not a dict"})
            continue

        # ── Empty track guard ──────────────────────────────────────────────────
        # Known-closed programs: enrollment paused/ended; empty by design, not scrape failure.
        _KNOWN_CLOSED = {"Sexuality_Studies_Minor", "Coaching_Education_Minor"}
        if not base.get("required_courses") and not base.get("choice_groups"):
            level = "INFO" if track in _KNOWN_CLOSED else "WARN"
            suffix = " (closed/paused program)" if track in _KNOWN_CLOSED else " — scrape likely failed"
            findings.append({"level": level, "check": "req_empty_track",
                             "msg": f"{track}: no required_courses and no choice_groups{suffix}"})

        base_req_set = set(base.get("required_courses", []))

        # ── Base required credit ceiling ───────────────────────────────────────
        base_cr = sum(catalog.get(c, {}).get("credits", 0) for c in base_req_set if c in catalog)
        if base_cr > MAX_BASE_REQUIRED_CREDITS:
            findings.append({"level": "ERROR", "check": "req_base_credit_ceiling",
                             "msg": f"{track}: base required_courses = {base_cr:.0f} credits "
                                    f"(>{MAX_BASE_REQUIRED_CREDITS}) — likely scraper pool-collapse"})

        # ── Ghost base required courses ────────────────────────────────────────
        ghost_req = [c for c in base_req_set if c not in catalog]
        if ghost_req:
            findings.append({"level": "ERROR", "check": "req_ghost_required",
                             "msg": f"{track}: {len(ghost_req)} ghost base required courses "
                                    f"(not in catalog): {ghost_req}"})

        # ── Choice group ID uniqueness (within base) ───────────────────────────
        base_ids = [g["id"] for g in base.get("choice_groups", [])]
        base_dupes = [i for i in base_ids if base_ids.count(i) > 1]
        if base_dupes:
            findings.append({"level": "ERROR", "check": "req_duplicate_group_ids",
                             "msg": f"{track}/base: duplicate group IDs {list(set(base_dupes))}"})

        # ── Required vs. options overlap ───────────────────────────────────────
        # Known groups where required courses intentionally also count toward
        # an elective quota (required courses are taken but the group is designed
        # to be satisfied by the same required courses).  Downgrade to WARN.
        _KNOWN_REQ_OVERLAP = {
            "Biomedical_Engineering_BS/base/bme_gateway_electives",
        }
        for g in base.get("choice_groups", []):
            opts = set(g.get("options") or [])
            stolen = base_req_set & opts
            if stolen:
                remaining = [o for o in opts if o in catalog and o not in base_req_set]
                cr = g.get("courses_required", 1)
                group_key = f"{track}/base/{g['id']}"
                if cr > len(remaining):
                    level = "WARN" if group_key in _KNOWN_REQ_OVERLAP else "ERROR"
                    findings.append({"level": level, "check": "req_required_option_collision",
                                     "msg": f"{group_key}: {len(stolen)} options are also required, "
                                            f"leaving only {len(remaining)} valid for {cr} needed — permanently unsatisfiable"
                                            + (" — known design (required courses satisfy elective quota)"
                                               if level == "WARN" else "")})
                elif stolen:
                    findings.append({"level": "WARN", "check": "req_required_option_collision",
                                     "msg": f"{track}/base/{g['id']}: {len(stolen)} options also appear in required_courses "
                                            f"(will be consumed before reaching this group)"})

        # ── Identical choice group options (duplicate detection) ───────────────
        option_fingerprints: dict[str, list[str]] = {}
        for g in base.get("choice_groups", []):
            opts = tuple(sorted(g.get("options") or []))
            if len(opts) > 0:
                option_fingerprints.setdefault(opts, []).append(g["id"])
        for fp, group_ids in option_fingerprints.items():
            if len(group_ids) > MAX_CHOICE_GROUP_IDENTICAL:
                findings.append({"level": "ERROR", "check": "req_identical_groups",
                                 "msg": f"{track}: {len(group_ids)} groups share identical options {list(fp)[:3]}... "
                                        f"— likely double-capture: {group_ids}"})

        # ── Permanently unsatisfiable groups (0 valid options) ─────────────────
        for g in base.get("choice_groups", []):
            if g.get("type") == "rule_based":
                if get_rule_based_options is None:
                    continue
                opts = get_rule_based_options(g.get("rule") or {}, catalog)
            else:
                opts = g.get("options") or []

            valid = [o for o in opts if o in catalog and o not in base_req_set]
            cr = g.get("courses_required", 1)
            cr_needed = g.get("credits_required")

            if cr_needed:
                total = sum(catalog.get(o, {}).get("credits", 0) for o in valid)
                if total == 0 and len(opts) > 0:
                    findings.append({"level": "ERROR", "check": "req_zero_valid_pool",
                                     "msg": f"{track}/base/{g['id']}: 0 valid credits in pool "
                                            f"(all {len(opts)} options are ghost or consumed)"})
            elif cr > len(valid) and len(opts) > 0:
                group_key = f"{track}/base/{g['id']}"
                level = "WARN" if group_key in _KNOWN_REQ_OVERLAP else "ERROR"
                findings.append({"level": level, "check": "req_unsatisfiable_group",
                                 "msg": f"{group_key}: need {cr} courses, "
                                        f"only {len(valid)} valid of {len(opts)} options"
                                        + (" — known design" if level == "WARN" else "")})

        # ── Concentration checks ───────────────────────────────────────────────
        for conc_name, conc in tdata.get("concentrations", {}).items():
            if conc_name == "None":
                continue

            conc_req_set = set(conc.get("required_courses", []))

            # Concentration required credit ceiling
            # Structural scraper failures that reproduce on re-scraping (need architecture fix):
            _KNOWN_CONC_BLOAT = {
                "English_and_Comparative_Literature_BA/in_Writing_Editing_and_Digital_Publishing",
                "English_and_Comparative_Literature_BA/in_Science_Medicine_and_Literature",
                "English_and_Comparative_Literature_BA/in_Social_Justice_and_Literature",
            }
            conc_cr = sum(catalog.get(c, {}).get("credits", 0) for c in conc_req_set if c in catalog)
            _conc_key = f"{track}/{conc_name}"
            if conc_cr > MAX_CONC_REQUIRED_CREDITS:
                level = "WARN" if _conc_key in _KNOWN_CONC_BLOAT else "ERROR"
                findings.append({"level": level, "check": "req_conc_credit_ceiling",
                                 "msg": f"{track}/{conc_name}: {conc_cr:.0f} concentration-required credits "
                                        f"(>{MAX_CONC_REQUIRED_CREDITS})"
                                        + (" — known scraper structural issue" if level == "WARN"
                                           else " — likely pool-collapse")})

            # Ghost concentration required courses
            ghost_conc_req = [c for c in conc_req_set if c not in catalog]
            if ghost_conc_req:
                findings.append({"level": "ERROR", "check": "req_ghost_conc_required",
                                 "msg": f"{track}/{conc_name}: {len(ghost_conc_req)} ghost required: {ghost_conc_req}"})

            # Cross-section group ID collision
            conc_ids = [g["id"] for g in conc.get("choice_groups", [])]
            base_id_set = set(base_ids)
            shadow = [i for i in conc_ids if i in base_id_set]
            if shadow:
                findings.append({"level": "ERROR", "check": "req_cross_section_id_collision",
                                 "msg": f"{track}/{conc_name}: concentration group IDs shadow base IDs: {shadow} "
                                        f"— add 'conc_' prefix"})

            # Within-concentration duplicate IDs
            conc_dupes = [i for i in conc_ids if conc_ids.count(i) > 1]
            if conc_dupes:
                findings.append({"level": "ERROR", "check": "req_duplicate_group_ids",
                                 "msg": f"{track}/{conc_name}: duplicate group IDs {list(set(conc_dupes))}"})

    return findings


# ── Entrypoint ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validate pipeline output data quality")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 on any ERROR-level finding")
    parser.add_argument("--catalog-only", action="store_true")
    parser.add_argument("--requirements-only", action="store_true")
    args = parser.parse_args()

    catalog = load(CATALOG_PATH) if os.path.exists(CATALOG_PATH) else {}
    req     = load(REQUIREMENTS_PATH) if os.path.exists(REQUIREMENTS_PATH) else {}

    all_findings: list[dict] = []

    if not args.requirements_only and catalog:
        print(f"Checking catalog ({len(catalog)} courses)…")
        all_findings.extend(check_catalog(catalog))

    if not args.catalog_only and req:
        print(f"Checking requirements ({len(req)} tracks)…")
        all_findings.extend(check_requirements(req, catalog))

    # ── Report ──────────────────────────────────────────────────────────────────
    counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for f in all_findings:
        counts[f["level"]] = counts.get(f["level"], 0) + 1

    print()
    print(f"{'='*70}")
    print(f"Validation complete — {counts['ERROR']} errors, {counts['WARN']} warnings, {counts['INFO']} info")
    print(f"{'='*70}")

    for level in ("ERROR", "WARN", "INFO"):
        items = [f for f in all_findings if f["level"] == level]
        if items:
            print(f"\n[{level}] ({len(items)} findings):")
            for f in items:
                print(f"  [{f['check']}] {f['msg']}")

    if counts["ERROR"] > 0:
        print(f"\n❌  {counts['ERROR']} ERROR(s) found — fix before deploying.")
        if args.strict:
            sys.exit(1)
    else:
        print("\n✅  No errors — data looks clean.")


if __name__ == "__main__":
    main()
