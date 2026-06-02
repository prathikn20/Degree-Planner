"""
tests/test_non_standard_courses.py
Relative Preference Constraint — Internships (93) and Honors (H).

Loads actual JSON data for catalog. Slots are synthetic to target the logic
precisely.  Non-standard course must appear FIRST in the candidate list so the
greedy Phase-1a naively picks it; the objective penalty + ILS must correct it.
"""

import sys
import os
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.planner.path_generator import solve_optimal_path

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

with open(os.path.join(_DATA_DIR, "course_catalog.json")) as _f:
    _REAL_CATALOG = json.load(_f)


def _make_catalog(*course_ids):
    """Build a minimal canon_catalog for a list of course IDs."""
    return {
        c: {"credits": 3, "depth": 1, "original_courses": [c]}
        for c in course_ids
    }


def _make_single_slot(slot_id, candidates, program_id="TEST"):
    return {
        "slot_id": slot_id,
        "program_id": program_id,
        "type": "single",
        "is_core": False,
        "candidates": candidates,
    }


def _run(slots, catalog):
    path, slot_map = solve_optimal_path(
        slots=slots,
        canon_catalog=catalog,
        credit_ledger={},
        macro_bindings={},
        blacklist={},
        remaining_semesters=8,
    )
    return path, slot_map


class TestNonStandardCoursePreference(unittest.TestCase):

    # ── Vector A: Internship avoided when standard alternative exists ──────────
    def test_A_internship_avoided(self):
        """Solver picks COMP401 over COMP293 (internship) even when COMP293 is listed first."""
        # Non-standard listed FIRST so greedy Phase-1a would naively pick it;
        # the ILS must correct via the objective penalty.
        catalog = _make_catalog("COMP293", "COMP401")
        slots = [_make_single_slot("TEST__req__elective__1", ["COMP293", "COMP401"])]
        path, _ = _run(slots, catalog)
        self.assertIn(
            "COMP401", path,
            f"Expected standard course COMP401 to be selected, got: {path}"
        )
        self.assertNotIn(
            "COMP293", path,
            f"Internship COMP293 must not be selected when standard alt exists, got: {path}"
        )

    # ── Vector B: Honors course avoided when standard alternative exists ───────
    def test_B_honors_avoided(self):
        """Solver picks MATH547 over MATH692H (honors) even when MATH692H is listed first."""
        catalog = _make_catalog("MATH692H", "MATH547")
        slots = [_make_single_slot("TEST__req__elective__2", ["MATH692H", "MATH547"])]
        path, _ = _run(slots, catalog)
        self.assertIn(
            "MATH547", path,
            f"Expected standard course MATH547 to be selected, got: {path}"
        )
        self.assertNotIn(
            "MATH692H", path,
            f"Honors MATH692H must not be selected when standard alt exists, got: {path}"
        )

    # ── Vector C: Forced edge case — only non-standard candidate ──────────────
    def test_C_forced_nonstandard_selected(self):
        """Solver picks BUSI493 (internship) when it is the only candidate — no crippling penalty."""
        catalog = _make_catalog("BUSI493")
        slots = [_make_single_slot("TEST__req__elective__3", ["BUSI493"])]
        path, _ = _run(slots, catalog)
        self.assertIn(
            "BUSI493", path,
            f"BUSI493 must be selected when it is the only candidate, got: {path}"
        )

    # ── Vector D: Both slots coexist without interfering ─────────────────────
    def test_D_mixed_slots_no_regression(self):
        """Standard course wins in slot with alt; non-standard wins alone — both coexist."""
        catalog = _make_catalog("COMP293", "COMP401", "DATA493")
        slots = [
            _make_single_slot("TEST__req__elective__4a", ["COMP293", "COMP401"]),
            _make_single_slot("TEST__req__elective__4b", ["DATA493"], program_id="TEST2"),
        ]
        path, _ = _run(slots, catalog)
        self.assertIn("COMP401", path,
                      f"COMP401 expected in mixed-slot scenario, got: {path}")
        self.assertIn("DATA493", path,
                      f"DATA493 expected (only candidate in its slot), got: {path}")


if __name__ == "__main__":
    unittest.main()
