"""
fix_additional_required_courses.py
-----------------------------------
Some programs have prerequisite/support courses in required_courses[] even
though the UNC catalog places them in the "Additional Requirements" section.
Because required_courses entries are always tagged is_core=True by the
algorithm, this inflates the core-size and makes the 50% exclusivity cap
too permissive (the cap allows more sharing) yet wastes budget on non-core
courses.

Fix: move those courses from required_courses into single-option
choice_groups with is_core=False.  The requirements-checker and greedy
selector treat a single-option choice_group identically to a required course
(the student still MUST take it), but the budget machinery now correctly
treats it as an additional requirement.

Programs fixed:
  Data_Science_BS:         MATH231, MATH232, MATH347
  Economics_BS:            MATH231, MATH232
  Statistics_and_Analytics_BS: COMP116, COMP110, MATH231, MATH232, MATH347
  Biostatistics_BSPH:      MATH231, MATH232, MATH233, BIOL101, MATH347
  Biology_BS:              CHEM101, CHEM102, CHEM261, MATH231

Run:
    python3 scripts/fix_additional_required_courses.py
"""
import json, os, re

REQ_PATH = "data/degree_requirements.json"

# Mapping: track_id → courses to demote from required_courses → choice_groups
DEMOTE = {
    # Courses that appear in the "Additional Requirements" catalog section
    # but were loaded into required_courses (which the algorithm always
    # treats as is_core=True, inflating the core-size calculation).
    "Computer_Science_BS": ["MATH231", "MATH232"],
    "Computer_Science_BA": ["MATH231"],
    "Data_Science_BS": ["MATH231", "MATH232", "MATH347"],
    "Mathematics_BS": ["MATH231", "MATH232"],
    "Economics_BS":    ["MATH231", "MATH232"],
    "Statistics_and_Analytics_BS": ["COMP116", "COMP110", "MATH231", "MATH232", "MATH347"],
    "Biostatistics_BSPH": ["MATH231", "MATH232", "MATH233", "BIOL101", "MATH347"],
    "Biology_BS":     ["CHEM101", "CHEM102", "CHEM261", "MATH231"],
    "Chemistry_BS":   ["BIOL101", "MATH232", "MATH233", "MATH383", "PHYS118", "PHYS119"],
    "Physics_BS":     ["PHYS118", "PHYS119", "MATH231", "MATH232", "MATH233", "MATH383",
                       "CHEM101", "CHEM102", "CHEM102L", "ASTR202", "CHEM101L"],
    "Neuroscience_BS": ["BIOL101", "BIOL103", "BIOL220", "CHEM101", "CHEM102", "CHEM241",
                        "CHEM241L", "CHEM261", "CHEM262", "CHEM262L", "MATH231", "MATH232"],
    "Psychology_BS":  ["BIOL101"],
    "Biomedical_Engineering_BS": ["CHEM101", "MATH231", "MATH232", "PHYS118", "BIOL101",
                                   "CHEM102", "CHEM261", "MATH233", "MATH383", "PHYS119"],
    "Exercise_and_Sport_Science_BS": ["BIOL101"],
}

COURSE_CODE_RE = re.compile(r'^[A-Z]{2,5}\d{2,4}[A-Z]?$')


def _course_id(code: str) -> str:
    """Deterministic group ID from a course code: 'MATH231' → 'MATH231_1'."""
    return f"{code}_1"


def demote_courses(requirements: dict) -> dict:
    """
    Move demoted courses from required_courses to is_core=False choice_groups.
    Returns a summary dict {track → [demoted courses]}.
    """
    summary = {}
    for track_id, to_demote in DEMOTE.items():
        mdata = requirements.get(track_id)
        if not mdata:
            print(f"  WARN: {track_id} not in requirements — skipping")
            continue

        base = mdata["base_requirements"]
        req  = base.get("required_courses", [])
        cg   = base.get("choice_groups", [])

        existing_ids  = {g["id"] for g in cg}
        existing_opts = {o for g in cg for o in g.get("options", [])}

        demoted = []
        new_req = []
        for course in req:
            if course in to_demote:
                gid = _course_id(course)
                if gid in existing_ids or course in existing_opts:
                    # Already represented in choice_groups — just remove from required
                    demoted.append(course)
                else:
                    # Create a new is_core=False single-option choice_group
                    cg.append({
                        "id":               gid,
                        "description":      course,
                        "type":             "explicit",
                        "courses_required": 1,
                        "options":          [course],
                        "rule":             None,
                        "is_core":          False,
                    })
                    existing_ids.add(gid)
                    demoted.append(course)
            else:
                new_req.append(course)

        base["required_courses"] = new_req
        base["choice_groups"]    = cg
        if demoted:
            summary[track_id] = demoted
            print(f"  {track_id}: demoted {demoted}")

    return summary


def main() -> None:
    with open(REQ_PATH) as f:
        requirements = json.load(f)

    print("Demoting additional-requirement courses from required_courses …\n")
    summary = demote_courses(requirements)

    tmp = REQ_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(requirements, f, indent=2, ensure_ascii=False)
    os.replace(tmp, REQ_PATH)

    print(f"\nDone. {sum(len(v) for v in summary.values())} courses demoted across "
          f"{len(summary)} programs → {REQ_PATH}")


if __name__ == "__main__":
    main()
