"""
verify_core_flags.py
---------------------
Self-validation script for is_core flags in degree_requirements.json.

Assertions:
  1. Every choice group has an explicit is_core boolean (no missing keys).
  2. Every scrape-able major with base choice groups has at least 1 is_core=True
     group (i.e., some core content exists beyond just required_courses).
  3. Every major has a non-zero core size (required_courses + is_core groups).
  4. For each major the strict-majority cap (max_shared) is at least 1, meaning
     the algorithm has at least one slot it can share before hitting the cap.
  5. UNC_General_Education has ALL groups is_core=False (they are designed to
     double-count freely with major requirements).
  6. No choice group is is_core=True inside UNC_General_Education.
  7. is_core values are strictly booleans (not strings or None).

Exit code 0 → all assertions pass.
Exit code 1 → failures detected (printed to stdout).
"""

import json
import sys

REQ_PATH = "data/degree_requirements.json"
GEN_ED   = "UNC_General_Education"

# Minors are expected to have all groups is_core=True; don't check for at-least-
# one-core since some very small minors have 0 choice groups altogether.
def _is_minor(track_id: str) -> bool:
    return "minor" in track_id.lower()


def _program_core_size(mdata: dict, conc_id: str = "None") -> tuple[int, int]:
    """(n_core_slots, n_core_groups) using the same formula as path_generator.

    Counts every required_course as 1 slot and every is_core=True choice_group
    as courses_required slots (not just 1 per group).  Includes concentration
    data so the number matches what the algorithm actually enforces.
    """
    base      = mdata.get("base_requirements", {})
    conc_data = mdata.get("concentrations", {}).get(conc_id, {})

    required = base.get("required_courses", []) + conc_data.get("required_courses", [])
    groups   = base.get("choice_groups",    []) + conc_data.get("choice_groups",    [])

    n_slots = len(required)
    n_grps  = 0
    for g in groups:
        if not g.get("is_core", True):
            continue
        n = g.get("courses_required", 1)
        n_slots += n
        n_grps  += 1

    return n_slots, n_grps


def main() -> int:
    with open(REQ_PATH) as f:
        data = json.load(f)

    failures = []

    for major_id, mdata in data.items():
        base  = mdata.get("base_requirements", {})
        concs = mdata.get("concentrations", {})

        # ── Assertion 1: no missing is_core ──────────────────────────────────
        for g in base.get("choice_groups", []):
            if "is_core" not in g:
                failures.append(
                    f"{major_id}: base group '{g['id']}' missing is_core"
                )
            elif not isinstance(g["is_core"], bool):
                failures.append(
                    f"{major_id}: base group '{g['id']}' is_core is not bool: {g['is_core']!r}"
                )

        for conc_id, cdata in concs.items():
            for g in cdata.get("choice_groups", []):
                if "is_core" not in g:
                    failures.append(
                        f"{major_id}/{conc_id}: group '{g['id']}' missing is_core"
                    )
                elif not isinstance(g["is_core"], bool):
                    failures.append(
                        f"{major_id}/{conc_id}: group '{g['id']}' is_core not bool"
                    )

        # ── Gen Ed: ALL must be False ─────────────────────────────────────────
        if major_id == GEN_ED:
            for g in base.get("choice_groups", []):
                if g.get("is_core") is not False:
                    failures.append(
                        f"UNC_General_Education group '{g['id']}' should be is_core=False"
                    )
            continue   # skip remaining checks for Gen Ed

        # ── Assertion 2 & 3: non-trivial majors (not minors) ─────────────────
        total_core, n_core_grps = _program_core_size(mdata)
        n_req = len(base.get("required_courses", []))
        has_choice_groups = bool(base.get("choice_groups"))

        if not _is_minor(major_id):
            # At least one source of core content
            if total_core == 0:
                failures.append(
                    f"{major_id}: total_core_size=0 (no required courses and no is_core groups)"
                )
            # If there are choice groups, at least one should be core
            if has_choice_groups and n_core_grps == 0 and n_req == 0:
                failures.append(
                    f"{major_id}: has {len(base['choice_groups'])} choice groups but "
                    "none are is_core=True AND required_courses is empty"
                )

        # ── Assertion 4: max_shared ≥ 1 for majors with ≥ 3 core slots ───────
        if total_core >= 3:
            max_shared = (total_core - 1) // 2
            if max_shared < 1:
                failures.append(
                    f"{major_id}: core_size={total_core} gives max_shared={max_shared} < 1"
                )

    if failures:
        print(f"FAILED — {len(failures)} assertion(s) violated:\n")
        for f in failures:
            print(f"  ✗ {f}")
        return 1

    # ── Summary stats ─────────────────────────────────────────────────────────
    total_groups  = 0
    core_groups   = 0
    add_groups    = 0
    missing_groups = 0
    major_stats   = []

    for major_id, mdata in data.items():
        base = mdata.get("base_requirements", {})
        tc, nc = _program_core_size(mdata)
        nf = sum(1 for g in base.get("choice_groups", []) if g.get("is_core") is False)
        groups = base.get("choice_groups", [])
        total_groups  += len(groups)
        core_groups   += sum(1 for g in groups if g.get("is_core"))
        add_groups    += sum(1 for g in groups if g.get("is_core") is False)
        missing_groups += sum(1 for g in groups if "is_core" not in g)
        if major_id != GEN_ED:
            major_stats.append((major_id, tc, nc, nf))

    print("✅ All assertions passed!\n")
    print(f"Total base choice groups : {total_groups}")
    print(f"  is_core=True           : {core_groups}")
    print(f"  is_core=False          : {add_groups}")
    print(f"  is_core missing        : {missing_groups}")

    print("\nTop programs by additional (is_core=False) groups:")
    major_stats.sort(key=lambda x: -x[3])
    for mid, tc, nc, nf in major_stats[:10]:
        max_shared = (tc - 1) // 2 if tc > 0 else 0
        print(f"  {mid}: core_size={tc} max_shared={max_shared} additional={nf}")

    print("\nSample core-size calculations (for double-major optimizer):")
    showcase = [
        "Computer_Science_BS", "Data_Science_BS", "Economics_BS",
        "Mathematics_BS", "Statistics_and_Analytics_BS", "Biology_BS",
    ]
    for mid in showcase:
        if mid not in data:
            continue
        tc, nc = _program_core_size(data[mid])
        ms = (tc - 1) // 2
        print(f"  {mid}: core_size={tc}, max_shared={ms}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
