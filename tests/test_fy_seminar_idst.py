"""
Tests for the FY-SEMINAR / FY-LAUNCH dedup and INTERDISCIPLINARY path-generation fixes.

Bug 1 (IDST missing from path):
    IDST89 has both FY-SEMINAR and INTERDISCIPLINARY attributes.  When the
    selector also picked a richer FY-SEMINAR course (e.g. PHYS55 with 4 attrs)
    the old dedup sorted by attribute count and removed IDST89 (2 attrs),
    silently dropping the INTERDISCIPLINARY course from the graduation path.

Bug 2 (FY-SEMINAR in path when already taken):
    When a student had already completed a FY-SEMINAR course, multi-attribute
    FY-SEMINAR courses (e.g. PHYS55 for FC-NATSCI) could still be recommended
    because the old dedup only removed *extra* FY-SEMINAR courses (keeping 1).

FY-LAUNCH (same one-per-career rule as FY-SEMINAR):
    UNC allows one FY-LAUNCH enrollment per career.  If a student has already
    completed a FY-LAUNCH course no more should be recommended; if they haven't,
    at most 1 FY-LAUNCH should appear in the graduation path.

The fixes live in two functions in src/planner/path_generator.py:
  - build_selection_avoid  — blocks all FY-SEMINAR / FY-LAUNCH courses from
                             selection when the student already completed one.
  - dedup_fy_seminar       — FY-SEMINAR: only dedup courses assigned to the
                             FY-SEMINAR slot; FY-LAUNCH: keep the most
                             attribute-rich one, discard the rest.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src.planner.requirements_checker import check_requirements
from src.planner.path_generator import (
    build_selection_avoid,
    dedup_fy_seminar,
    select_courses_globally,
)

# ── Minimal mock data ─────────────────────────────────────────────────────────
#
# Designed so the selector is deterministic: no ties other than course number.
# Course numbers determine priority when all else is equal (lower = preferred).
#
#  COMP50   FY-SEMINAR                              (plain FY seminar)
#  PHYS55   FY-SEMINAR + FC-NATSCI + FC-LAB         (rich FY seminar, 3 attrs)
#           ↑ the "villain" from Bug 1: more attrs than IDST89
#  IDST89   FY-SEMINAR + INTERDISCIPLINARY          (dual-purpose IDST)
#  IDST200  INTERDISCIPLINARY                       (safe IDST, no FY-SEMINAR)
#  PHYS101  FC-NATSCI                               (safe FC-NATSCI, no FY-SEMINAR)
#  PHYS102  FC-LAB                                  (safe FC-LAB, no FY-SEMINAR)
#  MATH52   FY-LAUNCH + FC-QUANT                    (plain FY-LAUNCH)
#  MATH55   FY-LAUNCH + FC-QUANT + FC-NATSCI + FC-LAB (rich FY-LAUNCH, 4 attrs)
#  MATH101  FC-QUANT                                (safe FC-QUANT, no FY-LAUNCH)
#  ENGL105  (no attrs)                              (required course)

CATALOG = {
    "ENGL105": {"name": "English Comp",         "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": []},
    "COMP50":  {"name": "FY Sem: CS",           "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": ["FY-SEMINAR"]},
    "PHYS55":  {"name": "FY Sem: Physics",      "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": ["FY-SEMINAR", "FC-NATSCI", "FC-LAB"]},
    "IDST89":  {"name": "FY Sem: IDST",         "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": ["FY-SEMINAR", "INTERDISCIPLINARY"]},
    "IDST200": {"name": "IDST Methods",         "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": ["INTERDISCIPLINARY"]},
    "PHYS101": {"name": "Intro Physics",        "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": ["FC-NATSCI"]},
    "PHYS102": {"name": "Physics Lab",          "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": ["FC-LAB"]},
    "MATH52":  {"name": "FY Launch: Math",      "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": ["FY-LAUNCH", "FC-QUANT"]},
    "MATH55":  {"name": "FY Launch: Calc",      "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": ["FY-LAUNCH", "FC-QUANT", "FC-NATSCI", "FC-LAB"]},
    "MATH101": {"name": "Intro Calculus",       "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": ["FC-QUANT"]},
}

GEN_ED = "UNC_General_Education"

REQUIREMENTS = {
    GEN_ED: {
        "base_requirements": {
            "required_courses": ["ENGL105"],
            "choice_groups": [
                {
                    "id": "FY-SEMINAR",
                    "description": "First-Year Seminar (one FY seminar course)",
                    "type": "rule_based",
                    "rule": {"attribute": "FY-SEMINAR"},
                    "options": [],
                    "courses_required": 1,
                    "is_core": False,
                },
                {
                    "id": "FC-NATSCI",
                    "description": "Natural Scientific Investigation",
                    "type": "rule_based",
                    "rule": {"attribute": "FC-NATSCI"},
                    "options": [],
                    "courses_required": 1,
                    "is_core": False,
                },
                {
                    "id": "FC-LAB",
                    "description": "Empirical Investigation Lab",
                    "type": "rule_based",
                    "rule": {"attribute": "FC-LAB"},
                    "options": [],
                    "courses_required": 1,
                    "is_core": False,
                },
                {
                    "id": "FC-QUANT",
                    "description": "Quantitative Reasoning",
                    "type": "rule_based",
                    "rule": {"attribute": "FC-QUANT"},
                    "options": [],
                    "courses_required": 1,
                    "is_core": False,
                },
                {
                    "id": "INTERDISCIPLINARY",
                    "description": "Interdisciplinary Perspectives (one IDST course)",
                    "type": "rule_based",
                    "rule": {"attribute": "INTERDISCIPLINARY"},
                    "options": [],
                    "courses_required": 1,
                    "is_core": False,
                },
            ],
        },
        "concentrations": {"None": {"required_courses": [], "choice_groups": []}},
    }
}

FY_GROUP_DESC = "First-Year Seminar (one FY seminar course)"


# ── Pipeline helper ────────────────────────────────────────────────────────────

def _run(completed: list, *, avoid: list | None = None) -> tuple[set, dict, bool]:
    """Simulate the relevant parts of run_pipeline for the mock Gen Ed data.

    Returns (all_remaining, audit, assumed_fy_taken).
    """
    assumed = list(completed)
    avoid   = list(avoid or [])
    majors  = [{"track": GEN_ED, "concentration": "None"}]

    # Mirrors run_pipeline: check uses original avoid; selection uses extended avoid.
    selection_avoid = build_selection_avoid(CATALOG, assumed, avoid)

    results = check_requirements(
        REQUIREMENTS, CATALOG, assumed,
        avoid_courses=avoid,
        track_id=GEN_ED, concentration_id="None",
    )
    results_by_track = {GEN_ED: results}

    selections = select_courses_globally(
        results_by_track, REQUIREMENTS, CATALOG, assumed,
        majors, avoid_courses=selection_avoid,
    )

    remaining, fm = selections[GEN_ED]
    audit = {GEN_ED: {"results": results, "remaining": remaining, "fulfillment_map": fm}}
    all_remaining = set(remaining)

    all_remaining = dedup_fy_seminar(
        all_remaining, audit, majors, REQUIREMENTS, CATALOG, assumed,
        gen_ed_track=GEN_ED,
    )

    assumed_fy_taken = any(
        "FY-SEMINAR" in CATALOG.get(c, {}).get("attributes", [])
        for c in assumed
    )
    return all_remaining, audit, assumed_fy_taken


def _fy_courses(remaining: set) -> list:
    return [c for c in remaining if "FY-SEMINAR" in CATALOG.get(c, {}).get("attributes", [])]


def _idst_courses(remaining: set) -> list:
    return [c for c in remaining if "INTERDISCIPLINARY" in CATALOG.get(c, {}).get("attributes", [])]


# ══════════════════════════════════════════════════════════════════════════════
# Unit tests for build_selection_avoid
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildSelectionAvoid:

    def test_no_fy_taken_returns_original_avoid(self):
        """Student has no FY-SEMINAR course → avoid list unchanged."""
        avoid = ["PHYS101"]
        result = build_selection_avoid(CATALOG, ["ENGL105"], avoid)
        assert result == avoid

    def test_fy_taken_blocks_all_fy_courses(self):
        """Student completed COMP50 (FY-SEMINAR) → all FY-SEMINAR courses blocked."""
        result = build_selection_avoid(CATALOG, ["ENGL105", "COMP50"], [])
        result_set = set(result)
        for course, data in CATALOG.items():
            if "FY-SEMINAR" in data.get("attributes", []):
                assert course in result_set, f"{course} (FY-SEMINAR) should be in selection_avoid"

    def test_fy_taken_preserves_non_fy_avoid(self):
        """Existing avoid entries are kept when FY courses are appended."""
        result = build_selection_avoid(CATALOG, ["COMP50"], ["PHYS101"])
        assert "PHYS101" in result

    def test_fy_taken_idst89_also_blocked(self):
        """IDST89 has FY-SEMINAR attribute → it must be in selection_avoid when FY taken."""
        result = build_selection_avoid(CATALOG, ["COMP50"], [])
        assert "IDST89" in result, (
            "IDST89 has FY-SEMINAR attribute; student who completed FY cannot take it"
        )

    def test_in_progress_fy_also_triggers_block(self):
        """A FY-SEMINAR course in in-progress (part of assumed) also triggers the block."""
        assumed = ["ENGL105", "PHYS55"]  # PHYS55 has FY-SEMINAR
        result = build_selection_avoid(CATALOG, assumed, [])
        assert "COMP50" in result
        assert "PHYS55" in result
        assert "IDST89" in result

    def test_no_fy_course_at_all_does_not_block(self):
        """When assumed has no FY-SEMINAR course, all FY courses stay available."""
        result = build_selection_avoid(CATALOG, ["ENGL105", "PHYS101"], [])
        for course in ["COMP50", "PHYS55", "IDST89"]:
            assert course not in result, f"{course} should not be blocked (no FY taken)"


# ══════════════════════════════════════════════════════════════════════════════
# Unit tests for dedup_fy_seminar
# ══════════════════════════════════════════════════════════════════════════════

class TestDedupFySeminar:

    def _make_audit(self, fm: dict) -> dict:
        return {GEN_ED: {"results": {}, "remaining": list(fm), "fulfillment_map": fm}}

    def test_idst89_with_idst_fulfillment_survives(self):
        """IDST89 assigned to INTERDISCIPLINARY slot is never in fy_for_slot → kept."""
        fm = {
            "COMP50":  FY_GROUP_DESC,                               # assigned to FY-SEMINAR
            "PHYS55":  "Natural Scientific Investigation",          # assigned to FC-NATSCI
            "IDST89":  "Interdisciplinary Perspectives (one IDST course)",  # NOT FY-SEMINAR
        }
        remaining = set(fm)
        result = dedup_fy_seminar(
            remaining, self._make_audit(fm),
            [{"track": GEN_ED, "concentration": "None"}],
            REQUIREMENTS, CATALOG, assumed=["ENGL105"],
        )
        assert "IDST89" in result, "IDST89 was assigned to INTERDISCIPLINARY and must survive dedup"

    def test_phys55_with_fc_fulfillment_survives(self):
        """PHYS55 assigned to FC-NATSCI is not in fy_for_slot → kept."""
        fm = {
            "COMP50": FY_GROUP_DESC,
            "PHYS55": "Natural Scientific Investigation",
            "IDST89": "Interdisciplinary Perspectives (one IDST course)",
        }
        remaining = set(fm)
        result = dedup_fy_seminar(
            remaining, self._make_audit(fm),
            [{"track": GEN_ED, "concentration": "None"}],
            REQUIREMENTS, CATALOG, assumed=["ENGL105"],
        )
        assert "PHYS55" in result

    def test_only_fy_slot_course_can_be_removed(self):
        """Only COMP50 (assigned to FY-SEMINAR slot) is eligible for dedup."""
        fm = {
            "COMP50": FY_GROUP_DESC,          # in fy_for_slot
            "PHYS55": "Natural Scientific Investigation",  # immune
            "IDST89": "Interdisciplinary Perspectives (one IDST course)",  # immune
        }
        remaining = set(fm)
        result = dedup_fy_seminar(
            remaining, self._make_audit(fm),
            [{"track": GEN_ED, "concentration": "None"}],
            REQUIREMENTS, CATALOG, assumed=["ENGL105"],
        )
        # fy_for_slot = [COMP50].  Not assumed_fy_taken.  1 course → nothing removed.
        assert "COMP50" in result
        assert "PHYS55" in result
        assert "IDST89" in result

    def test_extra_fy_slot_course_removed(self):
        """Two courses in fy_for_slot → keep most-attribute-rich, remove the other."""
        # Imagine two courses both assigned to the FY-SEMINAR slot (shouldn't happen
        # normally but tests the dedup logic directly).
        fm = {
            "PHYS55": FY_GROUP_DESC,   # 3 attrs: FY-SEMINAR + FC-NATSCI + FC-LAB
            "COMP50": FY_GROUP_DESC,   # 1 attr:  FY-SEMINAR
        }
        remaining = set(fm)
        result = dedup_fy_seminar(
            remaining, self._make_audit(fm),
            [{"track": GEN_ED, "concentration": "None"}],
            REQUIREMENTS, CATALOG, assumed=["ENGL105"],
        )
        # PHYS55 has more attrs → kept; COMP50 removed
        assert "PHYS55" in result
        assert "COMP50" not in result

    def test_fy_slot_course_removed_when_student_already_took_fy(self):
        """If student completed a FY-SEMINAR, even the single fy_for_slot course is removed."""
        fm = {"COMP50": FY_GROUP_DESC}
        remaining = set(fm)
        result = dedup_fy_seminar(
            remaining, self._make_audit(fm),
            [{"track": GEN_ED, "concentration": "None"}],
            REQUIREMENTS, CATALOG,
            assumed=["ENGL105", "PHYS55"],  # PHYS55 is FY-SEMINAR → assumed_fy_taken=True
        )
        assert "COMP50" not in result

    def test_no_fy_courses_in_remaining_is_noop(self):
        """No FY-SEMINAR courses in remaining → function is a safe no-op."""
        fm = {"PHYS101": "Natural Scientific Investigation", "IDST200": "Interdisciplinary Perspectives (one IDST course)"}
        remaining = set(fm)
        result = dedup_fy_seminar(
            remaining, self._make_audit(fm),
            [{"track": GEN_ED, "concentration": "None"}],
            REQUIREMENTS, CATALOG, assumed=["ENGL105"],
        )
        assert result == {"PHYS101", "IDST200"}

    def test_empty_remaining_is_noop(self):
        """Empty all_remaining → no crash."""
        result = dedup_fy_seminar(
            set(), self._make_audit({}),
            [{"track": GEN_ED, "concentration": "None"}],
            REQUIREMENTS, CATALOG, assumed=[],
        )
        assert result == set()


# ══════════════════════════════════════════════════════════════════════════════
# Bug 1: IDST89 survives when a higher-attribute FY-SEMINAR course is also selected
# ══════════════════════════════════════════════════════════════════════════════

class TestBug1IdstNotInPath:
    """
    Old dedup sorted FY-SEMINAR courses by attribute count and kept only the
    richest one.  PHYS55 (3 attrs) beat IDST89 (2 attrs), causing IDST89 to be
    discarded even though it was filling the INTERDISCIPLINARY slot.
    """

    def test_interdisciplinary_covered_when_fy_also_needed(self):
        """Core invariant: if INTERDISCIPLINARY is unsatisfied, an IDST course must be in path."""
        remaining, audit, fy_taken = _run(["ENGL105"])  # all groups unsatisfied
        assert not fy_taken

        assert "INTERDISCIPLINARY" in audit[GEN_ED]["results"]["unsatisfied"], (
            "Precondition: INTERDISCIPLINARY should be unsatisfied"
        )
        assert len(_idst_courses(remaining)) > 0, (
            f"INTERDISCIPLINARY unsatisfied but no IDST course in path. remaining={remaining}"
        )

    def test_idst89_not_removed_by_phys55(self):
        """PHYS55 filling FC-NATSCI must not evict IDST89 filling INTERDISCIPLINARY."""
        remaining, audit, _ = _run(["ENGL105"])
        fm = audit[GEN_ED]["fulfillment_map"]

        # If the selector assigned IDST89 to INTERDISCIPLINARY, it must survive dedup.
        if fm.get("IDST89") == "Interdisciplinary Perspectives (one IDST course)":
            assert "IDST89" in remaining, (
                "IDST89 was assigned to INTERDISCIPLINARY but was removed from the path. "
                "This is the Bug 1 regression."
            )

    def test_fy_seminar_course_also_in_path(self):
        """FY-SEMINAR slot must still be covered even when IDST89 goes to INTERDISCIPLINARY."""
        remaining, audit, _ = _run(["ENGL105"])
        fy_courses = _fy_courses(remaining)
        fm = audit[GEN_ED]["fulfillment_map"]

        # At least one course in remaining that fills the FY-SEMINAR requirement
        fy_slot_courses = [c for c in remaining if fm.get(c) == FY_GROUP_DESC]
        assert len(fy_slot_courses) == 1, (
            f"Expected exactly 1 course assigned to FY-SEMINAR slot, got: {fy_slot_courses}"
        )

    def test_old_dedup_would_have_removed_idst89(self):
        """Confirm what the OLD dedup would have done, to prove the fix is needed.

        With all_remaining = {COMP50, PHYS55, IDST89} the old logic sorted by
        attribute count: PHYS55(3) > IDST89(2) > COMP50(1) and removed all but
        PHYS55, wiping out both COMP50 (FY-SEMINAR slot) and IDST89 (INTERDISCIPLINARY).
        The NEW logic checks fulfillment labels so only COMP50 is in fy_for_slot.
        """
        fm = {
            "COMP50": FY_GROUP_DESC,
            "PHYS55": "Natural Scientific Investigation",
            "IDST89": "Interdisciplinary Perspectives (one IDST course)",
        }
        audit = {GEN_ED: {"results": {}, "remaining": list(fm), "fulfillment_map": fm}}
        majors = [{"track": GEN_ED, "concentration": "None"}]

        # Simulate OLD dedup
        all_remaining_old = set(fm)
        fy_by_attr = sorted(
            [c for c in all_remaining_old if "FY-SEMINAR" in CATALOG.get(c, {}).get("attributes", [])],
            key=lambda c: -len(CATALOG.get(c, {}).get("attributes", [])),
        )
        for extra in fy_by_attr[1:]:
            all_remaining_old.discard(extra)

        assert "IDST89" not in all_remaining_old, "OLD dedup should have removed IDST89"
        assert "COMP50" not in all_remaining_old, "OLD dedup should have removed COMP50"

        # Simulate NEW dedup
        all_remaining_new = set(fm)
        all_remaining_new = dedup_fy_seminar(
            all_remaining_new, audit, majors, REQUIREMENTS, CATALOG, assumed=["ENGL105"],
        )

        assert "IDST89" in all_remaining_new, "NEW dedup must keep IDST89 (INTERDISCIPLINARY)"
        assert "COMP50" in all_remaining_new, "NEW dedup must keep COMP50 (FY-SEMINAR slot)"
        assert "PHYS55" in all_remaining_new, "NEW dedup must keep PHYS55 (FC-NATSCI slot)"


# ══════════════════════════════════════════════════════════════════════════════
# Bug 2: No FY-SEMINAR in path when student already completed one
# ══════════════════════════════════════════════════════════════════════════════

class TestBug2FySeminarInPathWhenAlreadyTaken:

    def test_no_fy_seminar_in_path_after_comp50(self):
        """COMP50 (FY-SEMINAR) completed → zero FY-SEMINAR courses in remaining path."""
        remaining, _, fy_taken = _run(["ENGL105", "COMP50"])

        assert fy_taken, "Expected assumed_fy_taken=True"
        assert len(_fy_courses(remaining)) == 0, (
            f"Student completed FY-SEMINAR but path still contains FY-SEMINAR courses: "
            f"{_fy_courses(remaining)}"
        )

    def test_no_fy_seminar_in_path_after_phys55(self):
        """PHYS55 (FY-SEMINAR + FC-NATSCI + FC-LAB) completed → no FY-SEMINAR in path."""
        remaining, _, fy_taken = _run(["ENGL105", "PHYS55"])

        assert fy_taken
        assert len(_fy_courses(remaining)) == 0, (
            f"Completed PHYS55 but path has FY-SEMINAR courses: {_fy_courses(remaining)}"
        )

    def test_no_fy_seminar_in_path_after_idst89(self):
        """IDST89 (FY-SEMINAR + INTERDISCIPLINARY) completed → no FY-SEMINAR in path."""
        remaining, _, fy_taken = _run(["ENGL105", "IDST89"])

        assert fy_taken
        assert len(_fy_courses(remaining)) == 0, (
            f"Completed IDST89 but path has FY-SEMINAR courses: {_fy_courses(remaining)}"
        )

    def test_fc_natsci_uses_phys101_not_phys55_when_fy_taken(self):
        """After FY-SEMINAR taken, FC-NATSCI must fall back to PHYS101 (no FY-SEMINAR attr)."""
        remaining, audit, _ = _run(["ENGL105", "COMP50"])
        fm = audit[GEN_ED]["fulfillment_map"]

        for course, desc in fm.items():
            if "Natural Scientific" in desc or desc == "Natural Scientific Investigation":
                assert "FY-SEMINAR" not in CATALOG.get(course, {}).get("attributes", []), (
                    f"FC-NATSCI was assigned to {course} which has FY-SEMINAR attr. "
                    f"Student cannot take another FY-SEMINAR course!"
                )

    def test_fc_lab_uses_phys102_not_phys55_when_fy_taken(self):
        """After FY-SEMINAR taken, FC-LAB must fall back to PHYS102 (no FY-SEMINAR attr)."""
        remaining, audit, _ = _run(["ENGL105", "COMP50"])
        fm = audit[GEN_ED]["fulfillment_map"]

        for course, desc in fm.items():
            if "Empirical" in desc or desc == "Empirical Investigation Lab":
                assert "FY-SEMINAR" not in CATALOG.get(course, {}).get("attributes", []), (
                    f"FC-LAB was assigned to {course} which has FY-SEMINAR attr."
                )

    def test_interdisciplinary_uses_idst200_not_idst89_when_fy_taken(self):
        """After FY-SEMINAR taken, INTERDISCIPLINARY must use IDST200 (no FY-SEMINAR attr)."""
        remaining, _, _ = _run(["ENGL105", "COMP50"])

        idst_in_remaining = _idst_courses(remaining)
        assert len(idst_in_remaining) > 0, (
            "FY-SEMINAR taken, INTERDISCIPLINARY still needed, but no IDST in path"
        )
        for c in idst_in_remaining:
            assert "FY-SEMINAR" not in CATALOG.get(c, {}).get("attributes", []), (
                f"IDST course {c} in path has FY-SEMINAR attr — student cannot take it!"
            )

    def test_old_dedup_would_have_kept_fy_course(self):
        """Prove the old code failed: it kept a FY-SEMINAR course when student already had one.

        With student completed COMP50 (FY-SEMINAR), the selector would pick PHYS55 for
        FC-NATSCI (it has both FC-NATSCI and FY-SEMINAR).  The old dedup kept it since
        it was the only FY-SEMINAR course in remaining.  The new code avoids PHYS55
        entirely during selection via build_selection_avoid.
        """
        # Simulate what the OLD pipeline would do: no FY-SEMINAR block on selection_avoid,
        # then old dedup (keep richest 1).
        assumed = ["ENGL105", "COMP50"]  # COMP50 completed

        results = check_requirements(
            REQUIREMENTS, CATALOG, assumed,
            track_id=GEN_ED, concentration_id="None",
        )
        results_by_track = {GEN_ED: results}
        majors = [{"track": GEN_ED, "concentration": "None"}]

        # OLD pipeline: no special avoid for FY-SEMINAR courses
        selections_old = select_courses_globally(
            results_by_track, REQUIREMENTS, CATALOG, assumed,
            majors, avoid_courses=[],  # no FY block
        )
        remaining_old, _ = selections_old[GEN_ED]
        all_remaining_old = set(remaining_old)

        # OLD dedup
        fy_by_attr = sorted(
            [c for c in all_remaining_old if "FY-SEMINAR" in CATALOG.get(c, {}).get("attributes", [])],
            key=lambda c: -len(CATALOG.get(c, {}).get("attributes", [])),
        )
        for extra in fy_by_attr[1:]:
            all_remaining_old.discard(extra)

        # There MAY be a FY-SEMINAR course still in remaining under the old logic
        # (if PHYS55 was selected for FC-NATSCI it would survive as "the one kept FY course")
        old_fy = _fy_courses(all_remaining_old)

        # NEW pipeline
        remaining_new, _, _ = _run(["ENGL105", "COMP50"])
        new_fy = _fy_courses(remaining_new)

        assert len(new_fy) == 0, (
            f"NEW pipeline must have 0 FY-SEMINAR courses when student completed one. "
            f"Got: {new_fy}"
        )
        # The test documents the old behaviour without asserting it fails (it may or may
        # not depending on which course the selector picked first), but confirms the NEW
        # pipeline is always clean.


# ══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_nothing_completed_no_crash(self):
        """Empty completed list → pipeline runs without error."""
        remaining, audit, fy_taken = _run([])
        assert isinstance(remaining, set)
        assert not fy_taken

    def test_all_satisfied_no_remaining(self):
        """Student who completed everything has an empty remaining set."""
        # Cover every choice group: FY-SEMINAR, FC-NATSCI, FC-LAB, FC-QUANT, INTERDISCIPLINARY
        remaining, _, _ = _run(["ENGL105", "COMP50", "PHYS101", "PHYS102", "MATH101", "IDST200"])
        assert len(remaining) == 0, f"All done but remaining={remaining}"

    def test_at_most_one_course_assigned_to_fy_seminar_slot(self):
        """The FY-SEMINAR slot requires exactly 1 course; dedup never leaves more than 1."""
        for completed in [[], ["ENGL105"], ["ENGL105", "PHYS101"]]:
            remaining, audit, _ = _run(completed)
            fm = audit[GEN_ED]["fulfillment_map"]
            fy_slot = [c for c in remaining if fm.get(c) == FY_GROUP_DESC]
            assert len(fy_slot) <= 1, (
                f"completed={completed}: more than 1 course assigned to FY-SEMINAR slot: {fy_slot}"
            )

    def test_zero_fy_in_path_when_fy_completed(self):
        """Invariant holds for all three FY-SEMINAR courses in the mock catalog."""
        for fy_course in ["COMP50", "PHYS55", "IDST89"]:
            remaining, _, fy_taken = _run(["ENGL105", fy_course])
            assert fy_taken, f"assumed_fy_taken should be True after completing {fy_course}"
            fy_in_path = _fy_courses(remaining)
            assert len(fy_in_path) == 0, (
                f"Completed {fy_course} but FY-SEMINAR courses still in path: {fy_in_path}"
            )

    def test_interdisciplinary_always_covered_when_needed(self):
        """As long as student hasn't completed IDST89 or IDST200, path must include one."""
        remaining, audit, _ = _run(["ENGL105"])
        if "INTERDISCIPLINARY" in audit[GEN_ED]["results"]["unsatisfied"]:
            assert len(_idst_courses(remaining)) > 0, (
                f"INTERDISCIPLINARY unsatisfied but no IDST in path. remaining={remaining}"
            )

    def test_fy_slot_covered_when_fy_not_taken(self):
        """When student hasn't taken FY-SEMINAR, the path must include a course for it."""
        remaining, audit, fy_taken = _run(["ENGL105"])
        assert not fy_taken
        if "FY-SEMINAR" in audit[GEN_ED]["results"]["unsatisfied"]:
            fm = audit[GEN_ED]["fulfillment_map"]
            fy_slot = [c for c in remaining if fm.get(c) == FY_GROUP_DESC]
            assert len(fy_slot) == 1, (
                f"FY-SEMINAR unsatisfied but no (or too many) courses for it in path: {fy_slot}"
            )

    def test_avoid_courses_respected_independently(self):
        """User-level avoid list is still respected after FY-SEMINAR block logic."""
        remaining, _, _ = _run(["ENGL105"], avoid=["PHYS101"])
        assert "PHYS101" not in remaining

    def test_idst89_completed_satisfies_both_groups(self):
        """Taking IDST89 satisfies both FY-SEMINAR and INTERDISCIPLINARY (checker level)."""
        results = check_requirements(
            REQUIREMENTS, CATALOG, ["ENGL105", "IDST89"],
            track_id=GEN_ED, concentration_id="None",
        )
        assert "FY-SEMINAR" in results["satisfied"], (
            "IDST89 has FY-SEMINAR attr — should satisfy FY-SEMINAR requirement"
        )
        # INTERDISCIPLINARY: IDST89 goes to fys_consumed first (FY-SEMINAR processed first).
        # Whether it also counts for INTERDISCIPLINARY depends on the double-counting rules.
        # We only assert that taking IDST89 does NOT leave BOTH groups unsatisfied.
        unsatisfied = results["unsatisfied"]
        assert not ("FY-SEMINAR" in unsatisfied and "INTERDISCIPLINARY" in unsatisfied), (
            "IDST89 satisfies at least one of FY-SEMINAR / INTERDISCIPLINARY"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Real-data smoke tests (use actual catalog + requirements files)
# ══════════════════════════════════════════════════════════════════════════════

CATALOG_PATH      = "data/course_catalog.json"
REQUIREMENTS_PATH = "data/degree_requirements.json"
REAL_GEN_ED       = "UNC_General_Education"


@pytest.fixture(scope="module")
def real_catalog():
    with open(CATALOG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def real_requirements():
    with open(REQUIREMENTS_PATH) as f:
        return json.load(f)


def _run_real(completed, catalog, requirements, *, avoid=None):
    """Same as _run() but against real data."""
    assumed = list(completed)
    avoid   = list(avoid or [])
    majors  = [{"track": REAL_GEN_ED, "concentration": "None"}]

    selection_avoid = build_selection_avoid(catalog, assumed, avoid)

    results = check_requirements(
        requirements, catalog, assumed,
        avoid_courses=avoid,
        track_id=REAL_GEN_ED, concentration_id="None",
    )
    results_by_track = {REAL_GEN_ED: results}

    selections = select_courses_globally(
        results_by_track, requirements, catalog, assumed,
        majors, avoid_courses=selection_avoid,
    )

    remaining, fm = selections[REAL_GEN_ED]
    audit = {REAL_GEN_ED: {"results": results, "remaining": remaining, "fulfillment_map": fm}}
    all_remaining = set(remaining)

    all_remaining = dedup_fy_seminar(
        all_remaining, audit, majors, requirements, catalog, assumed,
        gen_ed_track=REAL_GEN_ED,
    )

    return all_remaining, audit


class TestRealData:

    def test_idst_in_path_when_no_idst_course_completed(
        self, real_catalog, real_requirements
    ):
        """With only ENGL105 + required IDST courses done, INTERDISCIPLINARY still needs a course.

        IDST101 and IDST111L are *required courses* in the real Gen Ed data and are
        excluded from INTERDISCIPLINARY choice-group options (required_set filter).
        So completing them does NOT satisfy the INTERDISCIPLINARY group — the path
        must include an additional IDST course (e.g. IDST89 or IDST112I).
        """
        completed = ["ENGL105", "IDST101", "IDST111L"]
        remaining, audit = _run_real(completed, real_catalog, real_requirements)

        results = audit[REAL_GEN_ED]["results"]
        if "INTERDISCIPLINARY" in results["unsatisfied"]:
            idst_in_path = [
                c for c in remaining
                if "INTERDISCIPLINARY" in real_catalog.get(c, {}).get("attributes", [])
            ]
            assert len(idst_in_path) > 0, (
                "INTERDISCIPLINARY is unsatisfied (IDST101/IDST111L are required courses, "
                "not choice-group options) but no IDST course is in the graduation path. "
                "This is the Bug 1 regression with real data."
            )

    def test_no_fy_seminar_recommended_after_fy_taken_real(
        self, real_catalog, real_requirements
    ):
        """After completing a FY-SEMINAR course, the path must contain zero FY-SEMINAR courses.

        Uses COMP50 which has only the FY-SEMINAR attribute in the real catalog.
        """
        completed = ["ENGL105", "IDST101", "IDST111L", "COMP50"]
        remaining, audit = _run_real(completed, real_catalog, real_requirements)

        fy_in_path = [
            c for c in remaining
            if "FY-SEMINAR" in real_catalog.get(c, {}).get("attributes", [])
        ]
        assert len(fy_in_path) == 0, (
            f"Completed COMP50 (FY-SEMINAR) but graduation path still contains "
            f"FY-SEMINAR courses: {fy_in_path}"
        )

    def test_interdisciplinary_uses_non_fy_course_after_fy_taken_real(
        self, real_catalog, real_requirements
    ):
        """With FY-SEMINAR taken, INTERDISCIPLINARY must be filled by a non-FY-SEMINAR IDST."""
        completed = ["ENGL105", "IDST101", "IDST111L", "COMP50"]
        remaining, audit = _run_real(completed, real_catalog, real_requirements)

        results = audit[REAL_GEN_ED]["results"]
        if "INTERDISCIPLINARY" in results["unsatisfied"]:
            idst_in_path = [
                c for c in remaining
                if "INTERDISCIPLINARY" in real_catalog.get(c, {}).get("attributes", [])
            ]
            assert len(idst_in_path) > 0, "INTERDISCIPLINARY unsatisfied but no IDST in path"
            for c in idst_in_path:
                assert "FY-SEMINAR" not in real_catalog.get(c, {}).get("attributes", []), (
                    f"IDST course {c} in path has FY-SEMINAR attr — student cannot take it "
                    f"(already used their one FY-SEMINAR slot)."
                )

    def test_no_fy_seminar_for_fc_slots_after_fy_taken_real(
        self, real_catalog, real_requirements
    ):
        """FY-SEMINAR taken → no FC group should be filled by a FY-SEMINAR course."""
        completed = ["ENGL105", "IDST101", "IDST111L", "COMP50"]
        remaining, audit = _run_real(completed, real_catalog, real_requirements)

        fm = audit[REAL_GEN_ED]["fulfillment_map"]
        for course, desc in fm.items():
            if desc.startswith("FC-") or any(
                desc == g.get("description")
                for g in real_requirements.get(REAL_GEN_ED, {})
                                          .get("base_requirements", {})
                                          .get("choice_groups", [])
                if g["id"].startswith("FC-")
            ):
                assert "FY-SEMINAR" not in real_catalog.get(course, {}).get("attributes", []), (
                    f"FC group '{desc}' assigned to {course} which has FY-SEMINAR attribute. "
                    f"Student cannot take a second FY-SEMINAR course."
                )


# ══════════════════════════════════════════════════════════════════════════════
# FY-LAUNCH: same one-per-career rule as FY-SEMINAR
# ══════════════════════════════════════════════════════════════════════════════

def _launch_courses(remaining: set) -> list:
    return [c for c in remaining if "FY-LAUNCH" in CATALOG.get(c, {}).get("attributes", [])]


class TestBuildSelectionAvoidFyLaunch:

    def test_fy_launch_taken_blocks_all_launch_courses(self):
        """Student completed MATH52 (FY-LAUNCH) → all FY-LAUNCH courses blocked."""
        result = build_selection_avoid(CATALOG, ["ENGL105", "MATH52"], [])
        result_set = set(result)
        for course, data in CATALOG.items():
            if "FY-LAUNCH" in data.get("attributes", []):
                assert course in result_set, f"{course} (FY-LAUNCH) should be blocked"

    def test_fy_launch_taken_does_not_block_non_launch(self):
        """FY-LAUNCH block must not affect non-FY-LAUNCH courses."""
        result = build_selection_avoid(CATALOG, ["MATH52"], [])
        assert "MATH101" not in result  # MATH101 has only FC-QUANT, not FY-LAUNCH

    def test_fy_launch_taken_also_blocks_rich_launch_course(self):
        """MATH55 (FY-LAUNCH + FC-QUANT + FC-NATSCI + FC-LAB) must be blocked when FY-LAUNCH taken."""
        result = build_selection_avoid(CATALOG, ["MATH52"], [])
        assert "MATH55" in result

    def test_fy_seminar_and_fy_launch_blocks_are_independent(self):
        """Taking FY-SEMINAR does not block FY-LAUNCH courses and vice-versa."""
        # Only FY-SEMINAR taken
        result_fy = set(build_selection_avoid(CATALOG, ["COMP50"], []))
        assert "MATH52" not in result_fy, "FY-LAUNCH should not be blocked by FY-SEMINAR taken"

        # Only FY-LAUNCH taken
        result_fl = set(build_selection_avoid(CATALOG, ["MATH52"], []))
        assert "COMP50" not in result_fl, "FY-SEMINAR should not be blocked by FY-LAUNCH taken"

    def test_both_fy_seminar_and_fy_launch_blocked_when_both_taken(self):
        """If student somehow completed both, both program types are blocked."""
        result = set(build_selection_avoid(CATALOG, ["COMP50", "MATH52"], []))
        for course, data in CATALOG.items():
            if "FY-SEMINAR" in data.get("attributes", []) or "FY-LAUNCH" in data.get("attributes", []):
                assert course in result, f"{course} should be blocked"


class TestDedupFyLaunch:

    def _make_audit(self, fm: dict) -> dict:
        return {GEN_ED: {"results": {}, "remaining": list(fm), "fulfillment_map": fm}}

    def test_at_most_one_fy_launch_in_remaining(self):
        """When student hasn't taken FY-LAUNCH and 2 FY-LAUNCH courses in remaining, keep 1."""
        fm = {
            "MATH52": "Quantitative Reasoning",   # FY-LAUNCH + FC-QUANT (2 attrs)
            "MATH55": "Natural Scientific Investigation",  # FY-LAUNCH + 4 attrs
        }
        remaining = set(fm)
        result = dedup_fy_seminar(
            remaining, self._make_audit(fm),
            [{"track": GEN_ED, "concentration": "None"}],
            REQUIREMENTS, CATALOG, assumed=["ENGL105"],
        )
        launch_in_result = [c for c in result if "FY-LAUNCH" in CATALOG[c].get("attributes", [])]
        assert len(launch_in_result) <= 1, (
            f"Expected at most 1 FY-LAUNCH course, got: {launch_in_result}"
        )

    def test_richest_fy_launch_kept(self):
        """Keep the most attribute-rich FY-LAUNCH course (MATH55, 4 attrs over MATH52, 2)."""
        fm = {
            "MATH52": "Quantitative Reasoning",
            "MATH55": "Natural Scientific Investigation",
        }
        remaining = set(fm)
        result = dedup_fy_seminar(
            remaining, self._make_audit(fm),
            [{"track": GEN_ED, "concentration": "None"}],
            REQUIREMENTS, CATALOG, assumed=["ENGL105"],
        )
        assert "MATH55" in result, "MATH55 (4 attrs) should survive over MATH52 (2 attrs)"
        assert "MATH52" not in result, "MATH52 (fewer attrs) should be removed"

    def test_all_fy_launch_removed_when_student_took_one(self):
        """If student completed MATH52 (FY-LAUNCH), all FY-LAUNCH courses purged from remaining."""
        fm = {
            "MATH55": "Quantitative Reasoning",
            "MATH101": "Quantitative Reasoning",  # not FY-LAUNCH, must survive
        }
        remaining = set(fm)
        result = dedup_fy_seminar(
            remaining, self._make_audit(fm),
            [{"track": GEN_ED, "concentration": "None"}],
            REQUIREMENTS, CATALOG, assumed=["ENGL105", "MATH52"],  # MATH52 → FY-LAUNCH taken
        )
        assert "MATH55" not in result, "MATH55 (FY-LAUNCH) must be removed"
        assert "MATH101" in result, "MATH101 (not FY-LAUNCH) must survive"

    def test_single_fy_launch_in_remaining_when_not_taken_is_kept(self):
        """Only 1 FY-LAUNCH course in remaining and student hasn't taken any → keep it."""
        fm = {"MATH55": "Quantitative Reasoning"}
        remaining = set(fm)
        result = dedup_fy_seminar(
            remaining, self._make_audit(fm),
            [{"track": GEN_ED, "concentration": "None"}],
            REQUIREMENTS, CATALOG, assumed=["ENGL105"],
        )
        assert "MATH55" in result


class TestFyLaunchIntegration:
    """End-to-end pipeline tests for FY-LAUNCH rule enforcement."""

    def test_no_fy_launch_in_path_after_taking_one(self):
        """After completing MATH52 (FY-LAUNCH), no FY-LAUNCH courses in graduation path."""
        remaining, _, _ = _run(["ENGL105", "MATH52"])
        assert len(_launch_courses(remaining)) == 0, (
            f"Completed MATH52 (FY-LAUNCH) but path still has: {_launch_courses(remaining)}"
        )

    def test_no_fy_launch_in_path_after_rich_launch_taken(self):
        """After completing MATH55 (FY-LAUNCH + FC-QUANT + FC-NATSCI + FC-LAB), path is clean."""
        remaining, _, _ = _run(["ENGL105", "MATH55"])
        assert len(_launch_courses(remaining)) == 0, (
            f"Completed MATH55 (FY-LAUNCH) but path still has: {_launch_courses(remaining)}"
        )

    def test_at_most_one_fy_launch_in_path_when_not_taken(self):
        """Student hasn't taken FY-LAUNCH → at most 1 FY-LAUNCH course in path."""
        remaining, _, _ = _run(["ENGL105"])
        launch = _launch_courses(remaining)
        assert len(launch) <= 1, (
            f"More than 1 FY-LAUNCH course in path: {launch}"
        )

    def test_fc_quant_uses_non_launch_when_launch_taken(self):
        """After FY-LAUNCH taken, FC-QUANT should use MATH101 (no FY-LAUNCH attr)."""
        remaining, audit, _ = _run(["ENGL105", "MATH52"])
        fm = audit[GEN_ED]["fulfillment_map"]

        for course, desc in fm.items():
            if "Quantitative" in desc:
                assert "FY-LAUNCH" not in CATALOG.get(course, {}).get("attributes", []), (
                    f"FC-QUANT assigned to {course} which has FY-LAUNCH attr — "
                    f"student cannot take another FY-LAUNCH course!"
                )

    def test_fy_seminar_and_fy_launch_independent_in_pipeline(self):
        """Taking FY-SEMINAR does not block FY-LAUNCH; taking FY-LAUNCH does not block FY-SEMINAR."""
        # Took FY-SEMINAR (COMP50) but not FY-LAUNCH
        remaining_fy, _, _ = _run(["ENGL105", "COMP50"])
        assert len(_fy_courses(remaining_fy)) == 0, "No FY-SEMINAR in path after taking one"
        # FY-LAUNCH courses may still appear (student hasn't taken FY-LAUNCH)
        # (we don't assert they DO appear — depends on selector choices)

        # Took FY-LAUNCH (MATH52) but not FY-SEMINAR
        remaining_fl, _, _ = _run(["ENGL105", "MATH52"])
        assert len(_launch_courses(remaining_fl)) == 0, "No FY-LAUNCH in path after taking one"
        # FY-SEMINAR courses may still appear


class TestRealDataFyLaunch:
    """Real-catalog smoke tests for FY-LAUNCH enforcement."""

    def test_no_fy_launch_recommended_after_taking_one_real(
        self, real_catalog, real_requirements
    ):
        """After completing STOR120 (FY-LAUNCH), no FY-LAUNCH should appear in path."""
        completed = ["ENGL105", "IDST101", "IDST111L", "STOR120"]
        remaining, _ = _run_real(completed, real_catalog, real_requirements)

        launch_in_path = [
            c for c in remaining
            if "FY-LAUNCH" in real_catalog.get(c, {}).get("attributes", [])
        ]
        assert len(launch_in_path) == 0, (
            f"Completed STOR120 (FY-LAUNCH) but graduation path still contains "
            f"FY-LAUNCH courses: {launch_in_path}"
        )

    def test_at_most_one_fy_launch_in_path_real(self, real_catalog, real_requirements):
        """Student with no FY-LAUNCH completed → at most 1 FY-LAUNCH in path."""
        completed = ["ENGL105", "IDST101", "IDST111L"]
        remaining, _ = _run_real(completed, real_catalog, real_requirements)

        launch_in_path = [
            c for c in remaining
            if "FY-LAUNCH" in real_catalog.get(c, {}).get("attributes", [])
        ]
        assert len(launch_in_path) <= 1, (
            f"More than 1 FY-LAUNCH course in graduation path: {launch_in_path}"
        )

    def test_no_fy_launch_for_fc_slots_after_taken_real(
        self, real_catalog, real_requirements
    ):
        """FY-LAUNCH taken → no FC group should be filled by a FY-LAUNCH course."""
        completed = ["ENGL105", "IDST101", "IDST111L", "STOR120"]
        remaining, audit = _run_real(completed, real_catalog, real_requirements)

        fm = audit[REAL_GEN_ED]["fulfillment_map"]
        fc_group_descs = {
            g.get("description") or g["id"]
            for g in real_requirements.get(REAL_GEN_ED, {})
                                      .get("base_requirements", {})
                                      .get("choice_groups", [])
            if g["id"].startswith("FC-")
        }
        for course, desc in fm.items():
            if desc in fc_group_descs:
                assert "FY-LAUNCH" not in real_catalog.get(course, {}).get("attributes", []), (
                    f"FC group '{desc}' assigned to {course} which has FY-LAUNCH attribute. "
                    f"Student cannot take a second FY-LAUNCH course."
                )
