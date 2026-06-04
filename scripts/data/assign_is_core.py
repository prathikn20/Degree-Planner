"""
assign_is_core.py
-----------------
Scrapes the UNC Academic Catalog for every major in degree_requirements.json,
identifies which choice groups belong to "Core Requirements" vs
"Additional Requirements" sections, then writes is_core=True/False into the
JSON for every group that currently lacks the flag.

Matching strategy (two independent signals, either suffices):

  Signal A – rule_text matching
    Collect all rule_text rows from 'additional' sections.  Filter out
    overly generic phrases ("N of the following", "Select one", etc.) that
    appear in core sections too — they produce false positives.
    Match a group description against each filtered additional text using a
    0.80 similarity threshold (high precision over recall).

  Signal B – course-pool intersection
    Collect all course codes listed in 'additional' sections.
    If ≥ 80% of a choice group's options appear in the additional pool,
    the group is additional.  This catches single-course prerequisites that
    appear as bare 'course' rows (not rule_text) in the catalog.

  Priority order:
    1. Already set (is_core present)   → keep as-is
    2. Concentration group             → True  (concentration ≡ core)
    3. Advisory ("strongly recommended", "highly encouraged") → False
    4. Signal A OR Signal B match      → False (additional)
    5. Default                         → True  (conservative)

Run:
    python3 scripts/assign_is_core.py
"""

import difflib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.scraper.requirements_scraper import scrape_major_requirements
from src.scraper.requirements_assembler import classify_section_type

# ── URL map ───────────────────────────────────────────────────────────────────

TARGET_TRACKS = {
    "Computer_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/computer-science-major-bs/",
    "Data_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/data-science-major-bs/",
    "Mathematics_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/mathematics-major-bs/",
    "Statistics_and_Analytics_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/statistics-analytics-majors-bs/",
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
    "Exercise_and_Sport_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-bs/",
    "Biomedical_Engineering_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/biomedical-engineering-major-bs/",
    "Biostatistics_BSPH":
        "https://catalog.unc.edu/undergraduate/programs-study/biostatistics-major-bsph/",
    "Business_Administration_BSBA":
        "https://catalog.unc.edu/undergraduate/programs-study/business-administration-major-bsba/",
    "Applied_Sciences_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/applied-sciences-major-bs/",
    "Earth_and_Marine_Sciences_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/earth-marine-sciences-major-bs/",
    "Environmental_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/environmental-science-bs/",
    "Information_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/information-science-major-bs/",
    "Neurodiagnostics_and_Sleep_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/neurodiagnostics-sleep-sciences-major-bs/",
    "Community_and_Global_Public_Health_BSPH":
        "https://catalog.unc.edu/undergraduate/programs-study/community-global-public-health-major-bsph/",
    "Health_Policy_and_Management_BSPH":
        "https://catalog.unc.edu/undergraduate/programs-study/health-policy-management-major-bsph/",
    "Nutrition_BSPH":
        "https://catalog.unc.edu/undergraduate/programs-study/nutrition-major-bsph/",
    "Political_Science_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/political-science-major-ba/",
    "Public_Policy_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/public-policy-major-ba/",
    "Sociology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/sociology-major-ba/",
    "Economics_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/economics-major-ba/",
    "Psychology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/psychology-major-ba/",
    "Computer_Science_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/computer-science-major-ba/",
    "Data_Science_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/data-science-major-ba/",
    "Mathematics_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/mathematics-major-ba/",
    "Biology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/biology-major-ba/",
    "Chemistry_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/chemistry-major-ba/",
    "Physics_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/physics-major-ba/",
    "Linguistics_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/linguistics-major-ba/",
    "Anthropology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/anthropology-major-ba/",
    "Medical_Anthropology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/medical-anthropology-major-ba/",
    "Global_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/global-studies-major-ba/",
    "Environmental_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/environmental-studies-major-ba/",
    "Peace_War_and_Defense_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/peace-war-defense-major-ba/",
    "Management_and_Society_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/management-society-major-ba/",
    "Communication_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/communication-studies-major-ba/",
    "Exercise_and_Sport_Science_Fitness_Professional_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-ba-fitness-professional/",
    "Exercise_and_Sport_Science_General_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-ba-general/",
    "Exercise_and_Sport_Science_Sport_Administration_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-ba-sport-administration/",
    "Computer_Science_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/computer-science-minor/",
    "Data_Science_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/data-science-minor/",
    "Mathematics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/mathematics-minor/",
    "Statistics_and_Analytics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/statistics-and-analytics-minor/",
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
    "Neuroscience_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/neuroscience-minor/",
    "Exercise_and_Sport_Science_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-minor/",
    "Information_Systems_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/information-systems-minor/",
    "Medical_Anthropology_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/medical-anthropology-minor/",
    "Marine_Sciences_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/marine-sciences-minor/",
    "Spanish_for_the_Professions_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/spanish-professions-minor/",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

_ADVISORY_RE = re.compile(
    r'\bstrongly\s+recommended\b|\bhighly\s+encouraged\b', re.IGNORECASE
)

# Generic catalog boilerplate patterns that appear in BOTH core and additional
# sections — useless for distinguishing them; exclude from the matching set.
_GENERIC_RE = re.compile(
    r'^(one|two|three|four|five|six|seven|\d+)\s+of\s+(the\s+)?following'
    r'|^(at\s+least\s+)?(one|two|three|four|five|six|seven|\d+)\s+of\s+(the\s+)?following'
    r'|^select\s+(one|two|three|four|five|\d+)(\s+of\s+(the\s+)?following)?\s*:?\s*$'
    r'|^(one|two|three|four|five|\d+)\s+from\s+(among\s+)?the\s+following'
    r'|^choose\s+(one|two|three|\d+)'
    # "N courses chosen from the following" — structural pool headers that
    # appear in BOTH core and additional sections; too generic to discriminate.
    r'|^(one|two|three|four|five|six|seven|\d+)\s+courses?\s+chosen\s+from\b'
    r'|^(one|two|three|four|five|six|seven|\d+)\s+(additional\s+)?courses?\s+from\b'
    r'|^(one|two|three|four|five|six|seven|\d+)\s+electives?\b'
    r'|^code\s*\|?\s*title'
    r'|^total\s+hours?'
    r'|^remaining\s+general\s+education',
    re.IGNORECASE
)


def _normalise(text: str) -> str:
    t = re.sub(r'\s+', ' ', text.lower().strip())
    t = re.sub(r'\s*\d+\s*$', '', t).strip()
    # Strip footnote superscripts like " 1", " 2" anywhere in text
    t = re.sub(r'\s+\d+\s*', ' ', t).strip()
    return t


def _is_specific_enough(text: str) -> bool:
    """Return True when the normalised text is long and specific enough to
    serve as a discriminating signal — short generic phrases are excluded."""
    nt = _normalise(text)
    if len(nt) < 25:
        return False
    if _GENERIC_RE.match(nt):
        return False
    return True


def get_additional_info(url: str) -> tuple[set[str], set[str]]:
    """
    Fetch a catalog page and return (additional_rule_texts, additional_courses).

    additional_rule_texts – normalised rule_text descriptions from 'additional'
                             sections that are specific enough to be discriminating.
    additional_courses    – course codes that appear in 'additional' sections.
    """
    try:
        result = scrape_major_requirements(url)
    except Exception as exc:
        print(f"  WARN: fetch failed: {exc}")
        return set(), set()

    additional_texts:   set[str] = set()
    additional_courses: set[str] = set()

    for s in result.get("sections", []):
        title = s.get("title", "")
        rows  = s.get("rows", [])
        stype = classify_section_type(title, rows)
        if stype != "additional":
            continue

        for row in rows:
            kind = row.get("kind")
            if kind == "rule_text":
                t = _normalise(row.get("text", ""))
                if t and _is_specific_enough(t):
                    additional_texts.add(t)
            elif kind in ("course", "or_alternative"):
                for code in row.get("codes", []):
                    if re.match(r"^[A-Z]{2,5}\d{2,4}[A-Z]?$", code):
                        additional_courses.add(code)

    return additional_texts, additional_courses


def is_group_additional(
    group: dict,
    additional_texts: set[str],
    additional_courses: set[str],
) -> bool:
    """
    Return True when a choice group should be classified as is_core=False
    (i.e. it comes from an 'Additional Requirements' section).
    """
    desc = group.get("description", "") or ""
    gid  = group.get("id", "")

    # Advisory labels are never core requirements
    if _ADVISORY_RE.search(desc) or _ADVISORY_RE.search(gid):
        return True

    # Signal A: specific rule_text similarity
    if desc and _is_specific_enough(desc):
        nd = _normalise(desc)
        for at in additional_texts:
            if nd in at or at in nd:
                return True
            if difflib.SequenceMatcher(None, nd, at).ratio() >= 0.80:
                return True

    # Signal B: course-pool intersection
    options = group.get("options", [])
    if options and additional_courses:
        in_additional = sum(1 for o in options if o in additional_courses)
        coverage = in_additional / len(options)
        # If ≥ 80% of the group's options are listed in an additional section,
        # treat the group as additional.
        if coverage >= 0.80:
            return True

    return False


# ── Main ─────────────────────────────────────────────────────────────────────

def apply_is_core_flags(requirements: dict, changes: dict) -> None:
    for major_id, mdata in requirements.items():
        if major_id == "UNC_General_Education":
            continue  # already all False — leave alone

        url = TARGET_TRACKS.get(major_id)
        add_texts, add_courses = set(), set()
        if url:
            print(f"  Fetching {major_id} …")
            add_texts, add_courses = get_additional_info(url)
            time.sleep(0.35)

        # ── Base requirements ────────────────────────────────────────────────
        for group in mdata.get("base_requirements", {}).get("choice_groups", []):
            if "is_core" in group:
                continue

            new_val = not is_group_additional(group, add_texts, add_courses)
            group["is_core"] = new_val
            changes.setdefault(major_id, []).append(
                (group["id"], "MISSING", new_val)
            )

        # ── Concentration requirements ───────────────────────────────────────
        for conc_id, cdata in mdata.get("concentrations", {}).items():
            for group in cdata.get("choice_groups", []):
                if "is_core" in group:
                    continue
                # Concentration groups are core for that track by definition.
                group["is_core"] = True
                changes.setdefault(major_id, []).append(
                    (group["id"], "MISSING", True)
                )


def main() -> None:
    req_path = "data/degree_requirements.json"
    tmp_path  = req_path + ".tmp"

    with open(req_path) as f:
        requirements = json.load(f)

    changes: dict = {}
    print("Assigning is_core flags …\n")
    apply_is_core_flags(requirements, changes)

    with open(tmp_path, "w") as f:
        json.dump(requirements, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, req_path)

    print("\n── Changes Summary ─────────────────────────────────────────────")
    updated_majors = 0
    for major, gchanges in changes.items():
        false_count = sum(1 for _, _, nv in gchanges if nv is False)
        true_count  = sum(1 for _, _, nv in gchanges if nv is True)
        if false_count or true_count:
            updated_majors += 1
        print(f"  {major}: {len(gchanges)} groups  (core={true_count} additional={false_count})")

    total_updated = sum(len(v) for v in changes.values())
    print(f"\nTotal: {total_updated} groups across {updated_majors} programs → {req_path}")


if __name__ == "__main__":
    main()
