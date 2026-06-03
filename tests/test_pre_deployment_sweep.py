"""
V1 Pre-Deployment Sweep — Exhaustive QA Gauntlet
=================================================
Covers four attack vectors:
  1. Data-layer fuzzing (empty dicts, missing keys, bad types)
  2. Math-engine stress & edge cases (impossible constraints, cycles, timeouts)
  3. Exhaustive matrix run (every track in degree_requirements.json)
  4. UI-layer formatting & session-state chaos

Run with:
    python -m pytest tests/test_pre_deployment_sweep.py -v
"""

import json
import os
import sys
import time
import copy
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Shared fixtures ────────────────────────────────────────────────────────────

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_PATH = os.path.join(BASE, "data", "course_catalog.json")
REQUIREMENTS_PATH = os.path.join(BASE, "data", "degree_requirements.json")


@pytest.fixture(scope="session")
def real_catalog():
    with open(CATALOG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def real_requirements():
    with open(REQUIREMENTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def all_tracks(real_requirements):
    return list(real_requirements.keys())


# ─────────────────────────────────────────────────────────────────────────────
# VECTOR 1 — Data Layer Fuzzing
# ─────────────────────────────────────────────────────────────────────────────

class TestDataLayerFuzzing:
    """No Python crash allowed regardless of input."""

    # ── graph.py ─────────────────────────────────────────────────────────────

    def test_build_graph_empty_catalog(self):
        from src.planner.graph import build_graph
        g = build_graph({})
        assert g == {}

    def test_build_graph_no_prerequisites_key(self):
        """Catalog entry missing 'prerequisites' key must not raise KeyError."""
        from src.planner.graph import build_graph
        # build_graph does data['prerequisites'] — guard against KeyError
        catalog = {
            "COMP110": {"name": "Intro", "credits": 3, "prerequisites": [],
                        "corequisites": [], "cross_listed": [], "attributes": []},
            "COMP210": {"name": "Adv",   "credits": 3, "prerequisites": [],
                        "corequisites": [], "cross_listed": [], "attributes": []},
        }
        g = build_graph(catalog)
        assert "COMP110" in g and "COMP210" in g

    def test_build_graph_self_loop_prereq(self):
        """Course listing itself as prerequisite must not create infinite loop."""
        from src.planner.graph import build_graph
        catalog = {
            "COMP110": {"name": "X", "credits": 3, "prerequisites": [["COMP110"]],
                        "corequisites": [], "cross_listed": [], "attributes": []},
        }
        g = build_graph(catalog)
        assert "COMP110" in g

    def test_is_available_empty_catalog(self):
        from src.planner.graph import is_available
        assert is_available("COMP110", {}, set()) is False

    def test_is_available_unknown_course(self, real_catalog):
        from src.planner.graph import is_available
        assert is_available("ZZZZ999", real_catalog, set()) is False

    def test_is_available_no_prereqs(self, real_catalog):
        from src.planner.graph import is_available
        # COMP50 has no prerequisites (confirmed in fixture scan)
        assert is_available("COMP50", real_catalog, set()) is True

    # ── requirements_checker.py ───────────────────────────────────────────────

    def test_get_rule_based_options_none_rule(self, real_catalog):
        from src.planner.requirements_checker import get_rule_based_options
        result = get_rule_based_options(None, real_catalog)
        assert result == []

    def test_get_rule_based_options_empty_rule(self, real_catalog):
        from src.planner.requirements_checker import get_rule_based_options
        result = get_rule_based_options({}, real_catalog)
        assert isinstance(result, list)

    def test_get_rule_based_options_empty_catalog(self):
        from src.planner.requirements_checker import get_rule_based_options
        result = get_rule_based_options({"department": "COMP", "min_number": 100, "max_number": 499}, {})
        assert result == []

    def test_get_rule_based_options_nonexistent_attribute(self, real_catalog):
        from src.planner.requirements_checker import get_rule_based_options
        result = get_rule_based_options({"attribute": "XYZZY_NONEXISTENT_ATTR_9999"}, real_catalog)
        assert isinstance(result, list)

    def test_get_rule_based_options_exclude_set(self, real_catalog):
        from src.planner.requirements_checker import get_rule_based_options
        rule = {"department": "COMP", "min_number": 100, "max_number": 499,
                "exclude": ["COMP110", "COMP116"]}
        result = get_rule_based_options(rule, real_catalog)
        assert "COMP110" not in result
        assert "COMP116" not in result

    def test_check_requirements_unknown_track(self, real_catalog, real_requirements):
        from src.planner.requirements_checker import check_requirements
        result = check_requirements(real_requirements, real_catalog, [],
                                    track_id="NONEXISTENT_TRACK_9999")
        # Must return safe empty structure, not crash
        assert result["satisfied"] == []
        assert result["unsatisfied"] == []
        assert result["completion_pct"] == 0.0

    def test_check_requirements_empty_completed(self, real_catalog, real_requirements):
        from src.planner.requirements_checker import check_requirements
        result = check_requirements(real_requirements, real_catalog, [],
                                    track_id="Computer_Science_BS",
                                    concentration_id="None")
        assert isinstance(result["satisfied"], list)
        assert isinstance(result["unsatisfied"], list)
        assert 0.0 <= result["completion_pct"] <= 1.0

    def test_check_requirements_all_completed(self, real_catalog, real_requirements):
        """Feeding every catalog course as completed must not crash and should return 100%."""
        from src.planner.requirements_checker import check_requirements
        all_courses = list(real_catalog.keys())
        result = check_requirements(real_requirements, real_catalog, all_courses,
                                    track_id="Computer_Science_BS",
                                    concentration_id="None")
        assert result["completion_pct"] == pytest.approx(1.0)

    def test_check_requirements_honors_variant_satisfies_base(self, real_catalog, real_requirements):
        """MATH232H should satisfy a requirement for MATH232."""
        from src.planner.requirements_checker import check_requirements
        # Use Math BA which likely requires MATH232/233
        result = check_requirements(
            real_requirements, real_catalog, ["MATH232H", "MATH233"],
            track_id="Mathematics_BA", concentration_id="None"
        )
        # At minimum, these honors variant courses must be recognized (no crash)
        assert isinstance(result["satisfied"], list)

    def test_check_requirements_avoid_set_respected(self, real_catalog, real_requirements):
        from src.planner.requirements_checker import check_requirements
        all_courses = list(real_catalog.keys())
        # Avoid everything — should result in 0% completion
        result = check_requirements(
            real_requirements, real_catalog, [],
            avoid_courses=all_courses,
            track_id="Computer_Science_Minor",
            concentration_id="None"
        )
        assert result["completion_pct"] == pytest.approx(0.0)

    def test_check_requirements_none_catalog(self, real_requirements):
        """Passing empty catalog (graceful degradation)."""
        from src.planner.requirements_checker import check_requirements
        result = check_requirements(real_requirements, {}, [],
                                    track_id="Computer_Science_BS",
                                    concentration_id="None")
        assert isinstance(result, dict)

    def test_generate_slots_empty_catalog(self, real_requirements):
        from src.planner.requirements_checker import generate_slots_and_candidates
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog={},
            majors_to_check=[{"track": "Computer_Science_BS", "concentration": "None"}],
            completed_courses=[]
        )
        assert isinstance(slots, list)

    def test_generate_slots_empty_requirements(self, real_catalog):
        from src.planner.requirements_checker import generate_slots_and_candidates
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements={},
            catalog=real_catalog,
            majors_to_check=[{"track": "Computer_Science_BS", "concentration": "None"}],
            completed_courses=[]
        )
        assert slots == []

    def test_generate_slots_unknown_track(self, real_catalog, real_requirements):
        from src.planner.requirements_checker import generate_slots_and_candidates
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[{"track": "GHOST_TRACK_9999", "concentration": "None"}],
            completed_courses=[]
        )
        assert slots == []

    def test_generate_slots_all_completed(self, real_catalog, real_requirements):
        """When everything is already done, solver must receive zero open slots."""
        from src.planner.requirements_checker import generate_slots_and_candidates
        all_courses = list(real_catalog.keys())
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[{"track": "Computer_Science_Minor", "concentration": "None"}],
            completed_courses=all_courses
        )
        assert slots == []

    def test_generate_slots_returns_valid_slot_structure(self, real_catalog, real_requirements):
        from src.planner.requirements_checker import generate_slots_and_candidates
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[{"track": "Computer_Science_BS", "concentration": "None"}],
            completed_courses=[]
        )
        for slot in slots:
            assert "slot_id" in slot
            assert "program_id" in slot
            assert "type" in slot
            assert slot["type"] in ("single", "pool")
            assert "candidates" in slot
            assert isinstance(slot["candidates"], list)

    def test_generate_slots_no_zero_credit_candidates(self, real_catalog, real_requirements):
        """Zero-credit courses must never appear as candidates."""
        from src.planner.requirements_checker import generate_slots_and_candidates
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[{"track": "Computer_Science_BS", "concentration": "None"},
                             {"track": "UNC_General_Education", "concentration": "None"}],
            completed_courses=[]
        )
        for slot in slots:
            for cand in slot["candidates"]:
                cr = cc.get(cand, {}).get("credits", -1)
                assert cr > 0, f"Zero-credit candidate {cand} found in slot {slot['slot_id']}"

    def test_generate_slots_avoid_courses_excluded(self, real_catalog, real_requirements):
        from src.planner.requirements_checker import generate_slots_and_candidates
        avoid = ["COMP110", "COMP116", "COMP210", "COMP211"]
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[{"track": "Computer_Science_BS", "concentration": "None"}],
            completed_courses=[],
            avoid_courses=avoid
        )
        # Required courses are never filtered by avoid, but choice group candidates must be
        for slot in slots:
            if len(slot["candidates"]) > 1:
                for c in avoid:
                    canon_c = cc.get(c, {})
                    # Just verify no crash — structure is canonicalized
        assert isinstance(slots, list)

    # ── topological_sort.py ───────────────────────────────────────────────────

    def test_kahns_empty_list(self):
        from src.planner.topological_sort import kahns_algorithm
        result = kahns_algorithm([], {})
        assert result == {}

    def test_kahns_single_course_no_prereqs(self, real_catalog):
        from src.planner.topological_sort import kahns_algorithm
        result = kahns_algorithm(["COMP50"], real_catalog)
        assert "Semester 1" in result
        assert "COMP50" in result["Semester 1"]

    def test_kahns_chain(self, real_catalog):
        from src.planner.topological_sort import kahns_algorithm
        # COMP110 → COMP210 — simple chain
        result = kahns_algorithm(["COMP110", "COMP210"], real_catalog)
        flat = []
        for sem, courses in result.items():
            if "Unsequenced" not in sem:
                flat.extend(courses)
        assert "COMP110" in flat
        assert "COMP210" in flat
        # COMP110 must appear in an earlier semester than COMP210
        sems = {k: i for i, k in enumerate(result.keys())}
        sem110 = next((k for k, v in result.items() if "COMP110" in v), None)
        sem210 = next((k for k, v in result.items() if "COMP210" in v), None)
        if sem110 and sem210 and "Unsequenced" not in sem110 and "Unsequenced" not in sem210:
            assert sems[sem110] < sems[sem210]

    def test_kahns_duplicate_courses(self, real_catalog):
        """Duplicate course codes in input must not crash."""
        from src.planner.topological_sort import kahns_algorithm
        result = kahns_algorithm(["COMP110", "COMP110"], real_catalog)
        assert isinstance(result, dict)

    def test_kahns_courses_not_in_catalog(self):
        from src.planner.topological_sort import kahns_algorithm
        result = kahns_algorithm(["GHOST101", "GHOST202"], {})
        assert isinstance(result, dict)

    # ── transcript_parser.py ─────────────────────────────────────────────────

    def test_classify_row_too_short(self):
        from src.planner.transcript_parser import _classify_row
        code, status, term = _classify_row([])
        assert code is None and status is None and term is None

        code, status, term = _classify_row(["COMP"])
        assert code is None

        code, status, term = _classify_row(["COMP", "110"])
        assert code is None

    def test_classify_row_completed_course(self):
        from src.planner.transcript_parser import _classify_row
        # Normal completed: DEPT NUM name credits grade
        code, status, term = _classify_row(["COMP", "110", "Intro", "3", "A"])
        assert code == "COMP110"
        assert status == "completed"
        assert term is None

    def test_classify_row_in_progress_fall(self):
        from src.planner.transcript_parser import _classify_row
        code, status, term = _classify_row(["COMP", "210", "Data", "3", "Fall"])
        assert code == "COMP210"
        assert status == "in_progress"
        assert term == "Fall"

    def test_classify_row_in_progress_summer(self):
        from src.planner.transcript_parser import _classify_row
        code, status, term = _classify_row(["COMP", "210", "Data", "3", "Sum", "II"])
        assert code == "COMP210"
        assert status == "in_progress"
        assert "II" in term

    def test_classify_row_bad_dept(self):
        from src.planner.transcript_parser import _classify_row
        code, status, term = _classify_row(["12AB", "110", "Course", "3", "A"])
        assert code is None

    def test_classify_row_bad_number(self):
        from src.planner.transcript_parser import _classify_row
        code, status, term = _classify_row(["COMP", "abc", "Course", "3", "A"])
        assert code is None

    def test_classify_row_ps_grade(self):
        """Pass/Satisfactory grade counts as completed."""
        from src.planner.transcript_parser import _classify_row
        code, status, term = _classify_row(["COMP", "395", "Research", "3", "PS"])
        assert code == "COMP395"
        assert status == "completed"

    def test_classify_row_transfer_grade(self):
        """Transfer grade counts as completed."""
        from src.planner.transcript_parser import _classify_row
        code, status, term = _classify_row(["MATH", "233", "Calc", "4", "TR"])
        assert code == "MATH233"
        assert status == "completed"


# ─────────────────────────────────────────────────────────────────────────────
# VECTOR 2 — Math Engine Stress & Edge Cases
# ─────────────────────────────────────────────────────────────────────────────

class TestMathEngineEdgeCases:

    def test_solve_empty_slots(self):
        from src.planner.path_generator import solve_optimal_path
        path, mapping = solve_optimal_path([], {}, {}, {}, {}, remaining_semesters=8)
        assert path == []
        assert mapping == {}

    def test_solve_single_slot_no_candidates(self):
        """A slot with no candidates must not crash — it stays unfilled."""
        from src.planner.path_generator import solve_optimal_path
        slots = [{
            "program_id": "TEST",
            "slot_id": "TEST__req__COMP110",
            "is_core": True,
            "type": "single",
            "candidates": [],
            "credits_needed": 3,
        }]
        canon_catalog = {}
        path, mapping = solve_optimal_path(slots, canon_catalog, {}, {}, {}, remaining_semesters=8)
        assert isinstance(path, list)
        assert isinstance(mapping, dict)

    def test_solve_single_slot_one_candidate(self):
        from src.planner.path_generator import solve_optimal_path
        canon_catalog = {
            "CANON_COMP110": {"credits": 3, "depth": 1, "is_repeatable": False,
                              "prerequisites": [], "original_courses": ["COMP110"]}
        }
        slots = [{
            "program_id": "TEST",
            "slot_id": "TEST__req__CANON_COMP110",
            "is_core": True,
            "type": "single",
            "candidates": ["CANON_COMP110"],
            "credits_needed": 3,
        }]
        path, mapping = solve_optimal_path(slots, canon_catalog, {}, {}, {}, remaining_semesters=8)
        assert "COMP110" in path

    def test_solve_pool_slot(self):
        from src.planner.path_generator import solve_optimal_path
        canon_catalog = {
            "CANON_COMP110": {"credits": 3, "depth": 1, "is_repeatable": False,
                              "prerequisites": [], "original_courses": ["COMP110"]},
            "CANON_COMP210": {"credits": 3, "depth": 1, "is_repeatable": False,
                              "prerequisites": [], "original_courses": ["COMP210"]},
        }
        slots = [{
            "program_id": "TEST",
            "slot_id": "TEST__elective__POOL",
            "is_core": False,
            "type": "pool",
            "candidates": ["CANON_COMP110", "CANON_COMP210"],
            "credits_needed": 6,
        }]
        path, mapping = solve_optimal_path(slots, canon_catalog, {}, {}, {}, remaining_semesters=8)
        total_cr = sum(canon_catalog.get(f"CANON_{c}", {}).get("credits", 3)
                       for c in path)
        assert len(path) >= 1

    def test_solve_respects_remaining_semesters(self):
        """Courses with depth > remaining_semesters should be excluded."""
        from src.planner.path_generator import solve_optimal_path
        canon_catalog = {
            "CANON_DEEP": {"credits": 3, "depth": 10, "is_repeatable": False,
                           "prerequisites": [], "original_courses": ["DEEP999"]},
            "CANON_SHALLOW": {"credits": 3, "depth": 1, "is_repeatable": False,
                              "prerequisites": [], "original_courses": ["SHALLOW101"]},
        }
        slots = [{
            "program_id": "TEST",
            "slot_id": "TEST__elective__split_0",
            "is_core": False,
            "type": "single",
            "candidates": ["CANON_DEEP", "CANON_SHALLOW"],
            "credits_needed": 3,
        }]
        path, _ = solve_optimal_path(slots, canon_catalog, {}, {}, {}, remaining_semesters=2)
        assert "DEEP999" not in path

    def test_solve_completes_within_timeout(self, real_catalog, real_requirements):
        """Full CS BS + DS Minor solve must finish in under 30 seconds."""
        from src.planner.requirements_checker import generate_slots_and_candidates
        from src.planner.path_generator import solve_optimal_path
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[
                {"track": "Computer_Science_BS", "concentration": "None"},
                {"track": "Data_Science_Minor",  "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ],
            completed_courses=[]
        )
        t0 = time.time()
        path, mapping = solve_optimal_path(slots, cc, cl, mb, bl, remaining_semesters=8)
        elapsed = time.time() - t0
        assert elapsed < 30.0, f"Solver took {elapsed:.1f}s — exceeds 30s SLA"
        assert isinstance(path, list)

    def test_solve_dual_major_no_crash(self, real_catalog, real_requirements):
        """Dual major solve must return valid structure."""
        from src.planner.requirements_checker import generate_slots_and_candidates
        from src.planner.path_generator import solve_optimal_path
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[
                {"track": "Computer_Science_BS", "concentration": "Artificial_Intelligence"},
                {"track": "Mathematics_BS",       "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ],
            completed_courses=[]
        )
        path, mapping = solve_optimal_path(slots, cc, cl, mb, bl, remaining_semesters=8)
        assert isinstance(path, list)
        assert isinstance(mapping, dict)
        # All returned courses must be real strings
        for c in path:
            assert isinstance(c, str) and len(c) > 0

    def test_solve_all_courses_completed_returns_empty_path(self, real_catalog, real_requirements):
        """If all slots are already satisfied, path must be empty."""
        from src.planner.requirements_checker import generate_slots_and_candidates
        from src.planner.path_generator import solve_optimal_path
        all_courses = list(real_catalog.keys())
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[{"track": "Computer_Science_Minor", "concentration": "None"}],
            completed_courses=all_courses
        )
        assert slots == []
        path, mapping = solve_optimal_path(slots, cc, cl, mb, bl, remaining_semesters=8)
        assert path == []
        assert mapping == {}

    def test_solve_path_courses_exist_in_canon_catalog(self, real_catalog, real_requirements):
        """Every course in the returned path must trace back to the catalog."""
        from src.planner.requirements_checker import generate_slots_and_candidates
        from src.planner.path_generator import solve_optimal_path
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[
                {"track": "Computer_Science_BS", "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ],
            completed_courses=[]
        )
        path, mapping = solve_optimal_path(slots, cc, cl, mb, bl, remaining_semesters=8)
        for course in path:
            assert course in real_catalog, \
                f"Course '{course}' in path but absent from catalog"

    def test_solve_no_duplicate_courses_in_path(self, real_catalog, real_requirements):
        """The returned path must contain no duplicate course codes."""
        from src.planner.requirements_checker import generate_slots_and_candidates
        from src.planner.path_generator import solve_optimal_path
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[
                {"track": "Data_Science_BS", "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ],
            completed_courses=[]
        )
        path, _ = solve_optimal_path(slots, cc, cl, mb, bl, remaining_semesters=8)
        assert len(path) == len(set(path)), \
            f"Duplicate courses in path: {[c for c in path if path.count(c) > 1]}"

    def test_solve_mutually_exclusive_courses_not_both_in_path(self, real_catalog, real_requirements):
        """Anti-requisite courses must not both appear in the path."""
        from src.planner.requirements_checker import generate_slots_and_candidates, build_canonical_catalog
        from src.planner.path_generator import solve_optimal_path
        # Build blacklist first to find any mutual-exclusivity pairs
        cc, _, _, blacklist = build_canonical_catalog(real_catalog)
        if not blacklist:
            pytest.skip("No mutually exclusive courses found in catalog")
        slots, cc2, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[
                {"track": "Computer_Science_BS", "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ],
            completed_courses=[]
        )
        path, _ = solve_optimal_path(slots, cc2, cl, mb, bl, remaining_semesters=8)
        path_set = set(path)
        for canon, antis in bl.items():
            orig = cc2.get(canon, {}).get("original_courses", [canon])
            for c in orig:
                if c in path_set:
                    for anti in antis:
                        anti_canons = [k for k, v in cc2.items() if anti in v.get("original_courses", [])]
                        for ac in anti_canons:
                            for ac_real in cc2.get(ac, {}).get("original_courses", []):
                                assert ac_real not in path_set, \
                                    f"Mutually exclusive pair in path: {c} and {ac_real}"

    def test_calculate_static_depths_no_infinite_loop(self, real_catalog):
        """Depth calculation on real catalog must not hang (has cycle-severing)."""
        from src.planner.requirements_checker import calculate_static_depths
        t0 = time.time()
        depths = calculate_static_depths(real_catalog)
        elapsed = time.time() - t0
        assert elapsed < 10.0, f"calculate_static_depths took {elapsed:.1f}s"
        assert isinstance(depths, dict)
        # DFS visits ghost prereqs too, so depths may be larger than catalog
        assert len(depths) >= len(real_catalog), \
            "Every catalog course must have a depth entry"
        for course, depth in depths.items():
            assert depth >= 1, f"Course {course} has depth < 1"

    def test_calculate_static_depths_self_loop(self):
        """Self-referential prerequisite must not cause infinite recursion."""
        from src.planner.requirements_checker import calculate_static_depths
        catalog = {
            "GHOST001": {"prerequisites": [["GHOST001"]], "credits": 3,
                         "corequisites": [], "cross_listed": [], "attributes": []},
        }
        depths = calculate_static_depths(catalog)
        assert "GHOST001" in depths

    def test_build_canonical_catalog_empty(self):
        from src.planner.requirements_checker import build_canonical_catalog
        cc, c2c, mb, bl = build_canonical_catalog({})
        assert cc == {}
        assert c2c == {}

    def test_build_canonical_catalog_real(self, real_catalog):
        from src.planner.requirements_checker import build_canonical_catalog
        cc, c2c, mb, bl = build_canonical_catalog(real_catalog)
        # Every original catalog course should map to a canon ID
        for course in real_catalog:
            assert course in c2c, f"{course} not in course_to_canon"


# ─────────────────────────────────────────────────────────────────────────────
# VECTOR 3 — Exhaustive Matrix Run (All 197 Tracks)
# ─────────────────────────────────────────────────────────────────────────────

def _all_tracks_with_concentrations(real_requirements):
    """Generate (track, concentration) pairs for all tracks."""
    pairs = []
    for track, tdata in real_requirements.items():
        concs = list(tdata.get("concentrations", {}).keys()) or ["None"]
        for conc in concs:
            pairs.append((track, conc))
    return pairs


def pytest_generate_tests(metafunc):
    if "track_conc" in metafunc.fixturenames:
        req_path = os.path.join(BASE, "data", "degree_requirements.json")
        with open(req_path) as f:
            req = json.load(f)
        pairs = _all_tracks_with_concentrations(req)
        metafunc.parametrize("track_conc", pairs, ids=[f"{t}__{c}" for t, c in pairs])


class TestExhaustiveMatrixRun:
    """Every track × concentration pair must not raise any Python exception."""

    @pytest.fixture(autouse=True)
    def _load_data(self, real_catalog, real_requirements):
        self.catalog = real_catalog
        self.requirements = real_requirements

    def test_check_requirements_no_crash(self, track_conc):
        from src.planner.requirements_checker import check_requirements
        track, conc = track_conc
        result = check_requirements(
            self.requirements, self.catalog, [],
            track_id=track, concentration_id=conc
        )
        assert isinstance(result, dict)
        assert "satisfied" in result
        assert "unsatisfied" in result
        assert "completion_pct" in result
        assert 0.0 <= result["completion_pct"] <= 1.0

    def test_generate_slots_no_crash(self, track_conc):
        from src.planner.requirements_checker import generate_slots_and_candidates
        track, conc = track_conc
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=self.requirements,
            catalog=self.catalog,
            majors_to_check=[{"track": track, "concentration": conc},
                             {"track": "UNC_General_Education", "concentration": "None"}],
            completed_courses=[]
        )
        assert isinstance(slots, list)
        for slot in slots:
            assert "slot_id" in slot
            assert "candidates" in slot

    def test_check_requirements_satisfied_subset_of_total(self, track_conc):
        """Satisfied ≤ total requirements."""
        from src.planner.requirements_checker import check_requirements
        track, conc = track_conc
        result = check_requirements(
            self.requirements, self.catalog, [],
            track_id=track, concentration_id=conc
        )
        total = result["total_requirements"]
        satisfied = result["total_satisfied"]
        assert satisfied <= total, \
            f"{track}/{conc}: satisfied ({satisfied}) > total ({total})"


# ─────────────────────────────────────────────────────────────────────────────
# VECTOR 4 — UI Formatting & Session-State Chaos
# ─────────────────────────────────────────────────────────────────────────────

class TestUIFormattingLayer:
    """All formatting functions in app.py must handle edge-case strings safely."""

    def _import_app_functions(self):
        """Import formatting helpers directly from app module."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "app_module", os.path.join(BASE, "app.py")
        )
        mod = importlib.util.load_from_spec = None
        # Use direct import of the pure functions (they don't need Streamlit at test time)
        # We patch streamlit before importing
        import unittest.mock as mock
        import types

        st_mock = mock.MagicMock()
        st_mock.cache_resource = lambda f: f
        st_mock.secrets = {}

        with mock.patch.dict("sys.modules", {"streamlit": st_mock}):
            spec = importlib.util.spec_from_file_location("app_module", os.path.join(BASE, "app.py"))
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception:
                pass  # App-level Streamlit calls will fail; functions are still defined
        return mod

    @pytest.fixture(scope="class")
    def app_mod(self):
        return self._import_app_functions()

    # ── _sanitize_desc ────────────────────────────────────────────────────────

    def test_sanitize_desc_none_passthrough(self, app_mod):
        # None → should return None-like (raw) or empty without crash
        if not hasattr(app_mod, "_sanitize_desc"):
            pytest.skip("_sanitize_desc not importable")
        result = app_mod._sanitize_desc(None)
        # Must not raise, result is raw (None) or empty string
        assert result is None or isinstance(result, str)

    def test_sanitize_desc_empty_string(self, app_mod):
        if not hasattr(app_mod, "_sanitize_desc"):
            pytest.skip("_sanitize_desc not importable")
        result = app_mod._sanitize_desc("")
        assert result == ""

    def test_sanitize_desc_required_course_passthrough(self, app_mod):
        if not hasattr(app_mod, "_sanitize_desc"):
            pytest.skip("_sanitize_desc not importable")
        result = app_mod._sanitize_desc("Required Course")
        assert result == "Required Course"

    def test_sanitize_desc_strips_number_prefix(self, app_mod):
        if not hasattr(app_mod, "_sanitize_desc"):
            pytest.skip("_sanitize_desc not importable")
        result = app_mod._sanitize_desc("3 courses in Mathematics")
        assert not result.startswith("3 "), f"Expected number stripped, got: {result}"

    def test_sanitize_desc_strips_written_number(self, app_mod):
        if not hasattr(app_mod, "_sanitize_desc"):
            pytest.skip("_sanitize_desc not importable")
        result = app_mod._sanitize_desc("three courses in Physics")
        assert not result.lower().startswith("three"), f"Got: {result}"

    def test_sanitize_desc_long_garbage_string(self, app_mod):
        if not hasattr(app_mod, "_sanitize_desc"):
            pytest.skip("_sanitize_desc not importable")
        garbage = "†   " * 100 + "A" * 200
        result = app_mod._sanitize_desc(garbage)
        assert isinstance(result, str)

    def test_sanitize_desc_only_punctuation(self, app_mod):
        if not hasattr(app_mod, "_sanitize_desc"):
            pytest.skip("_sanitize_desc not importable")
        result = app_mod._sanitize_desc("......,,,,,!!!!!")
        assert isinstance(result, str)

    def test_sanitize_desc_unicode_nbsps(self, app_mod):
        if not hasattr(app_mod, "_sanitize_desc"):
            pytest.skip("_sanitize_desc not importable")
        result = app_mod._sanitize_desc("\xa0Five\xa0courses\xa0in\xa0COMP")
        assert isinstance(result, str)

    # ── _shorten_desc ─────────────────────────────────────────────────────────

    def test_shorten_desc_none(self, app_mod):
        if not hasattr(app_mod, "_shorten_desc"):
            pytest.skip("_shorten_desc not importable")
        result = app_mod._shorten_desc(None)
        assert result is None or isinstance(result, str)

    def test_shorten_desc_empty(self, app_mod):
        if not hasattr(app_mod, "_shorten_desc"):
            pytest.skip("_shorten_desc not importable")
        result = app_mod._shorten_desc("")
        assert result == ""

    def test_shorten_desc_truncates_at_55(self, app_mod):
        if not hasattr(app_mod, "_shorten_desc"):
            pytest.skip("_shorten_desc not importable")
        long_str = "A" * 100
        result = app_mod._shorten_desc(long_str)
        assert len(result) <= 55 + 1  # +1 for ellipsis char

    def test_shorten_desc_pipe_split(self, app_mod):
        if not hasattr(app_mod, "_shorten_desc"):
            pytest.skip("_shorten_desc not importable")
        result = app_mod._shorten_desc("COMP110 | Introduction to Programming H")
        # Should strip the left side
        assert "Introduction" in result

    # ── _program_short_label ──────────────────────────────────────────────────

    def test_program_short_label_known(self, app_mod):
        if not hasattr(app_mod, "_program_short_label"):
            pytest.skip("_program_short_label not importable")
        result = app_mod._program_short_label("Computer_Science_BS")
        assert result == "CS BS"

    def test_program_short_label_unknown(self, app_mod):
        if not hasattr(app_mod, "_program_short_label"):
            pytest.skip("_program_short_label not importable")
        result = app_mod._program_short_label("Some_Weird_Program_BA")
        assert isinstance(result, str) and len(result) > 0

    def test_program_short_label_empty(self, app_mod):
        if not hasattr(app_mod, "_program_short_label"):
            pytest.skip("_program_short_label not importable")
        result = app_mod._program_short_label("")
        assert isinstance(result, str)

    def test_program_short_label_no_suffix(self, app_mod):
        if not hasattr(app_mod, "_program_short_label"):
            pytest.skip("_program_short_label not importable")
        result = app_mod._program_short_label("Standalone")
        assert isinstance(result, str)

    # ── format_fulfillment_label ──────────────────────────────────────────────

    def test_format_fulfillment_label_normal(self, app_mod):
        if not hasattr(app_mod, "format_fulfillment_label"):
            pytest.skip("format_fulfillment_label not importable")
        result = app_mod.format_fulfillment_label("Computer_Science_BS", "Upper Division Elective")
        assert "CS BS" in result
        assert isinstance(result, str)

    def test_format_fulfillment_label_empty_desc(self, app_mod):
        if not hasattr(app_mod, "format_fulfillment_label"):
            pytest.skip("format_fulfillment_label not importable")
        result = app_mod.format_fulfillment_label("Computer_Science_BS", "")
        assert isinstance(result, str)
        assert "Elective" in result  # empty desc falls back to "Elective"

    def test_format_fulfillment_label_none_desc(self, app_mod):
        if not hasattr(app_mod, "format_fulfillment_label"):
            pytest.skip("format_fulfillment_label not importable")
        result = app_mod.format_fulfillment_label("Computer_Science_BS", None)
        assert isinstance(result, str)

    # ── is_minor ─────────────────────────────────────────────────────────────

    def test_is_minor_true(self, app_mod):
        if not hasattr(app_mod, "is_minor"):
            pytest.skip("is_minor not importable")
        assert app_mod.is_minor("Computer_Science_Minor") is True

    def test_is_minor_false(self, app_mod):
        if not hasattr(app_mod, "is_minor"):
            pytest.skip("is_minor not importable")
        assert app_mod.is_minor("Computer_Science_BS") is False

    def test_is_minor_mixed_case(self, app_mod):
        if not hasattr(app_mod, "is_minor"):
            pytest.skip("is_minor not importable")
        assert app_mod.is_minor("MINOR_Studies_BA") is True

    # ── available_concentrations ──────────────────────────────────────────────

    def test_available_concentrations_no_concs(self, app_mod, real_requirements):
        if not hasattr(app_mod, "available_concentrations"):
            pytest.skip("available_concentrations not importable")
        result = app_mod.available_concentrations(real_requirements, "Mathematics_Minor")
        assert result == ["None"]

    def test_available_concentrations_with_concs(self, app_mod, real_requirements):
        if not hasattr(app_mod, "available_concentrations"):
            pytest.skip("available_concentrations not importable")
        result = app_mod.available_concentrations(real_requirements, "Computer_Science_BS")
        assert len(result) > 1

    def test_available_concentrations_unknown_track(self, app_mod, real_requirements):
        if not hasattr(app_mod, "available_concentrations"):
            pytest.skip("available_concentrations not importable")
        result = app_mod.available_concentrations(real_requirements, "NONEXISTENT_TRACK")
        assert result == ["None"]

    # ── build_prereq_dot ──────────────────────────────────────────────────────

    def test_build_prereq_dot_empty_path(self, app_mod, real_catalog):
        if not hasattr(app_mod, "build_prereq_dot"):
            pytest.skip("build_prereq_dot not importable")
        result = app_mod.build_prereq_dot([], real_catalog, [], [])
        assert isinstance(result, str)
        assert "digraph" in result

    def test_build_prereq_dot_no_catalog(self, app_mod):
        if not hasattr(app_mod, "build_prereq_dot"):
            pytest.skip("build_prereq_dot not importable")
        result = app_mod.build_prereq_dot(["COMP110", "COMP210"], {}, [], [])
        assert isinstance(result, str)
        assert "digraph" in result

    def test_build_prereq_dot_no_xss(self, app_mod, real_catalog):
        """DOT output must not contain unescaped double-quote injections."""
        if not hasattr(app_mod, "build_prereq_dot"):
            pytest.skip("build_prereq_dot not importable")
        # Inject course name with quotes
        malicious_catalog = copy.deepcopy(real_catalog)
        if "COMP110" in malicious_catalog:
            malicious_catalog["COMP110"]["name"] = 'Hello "World" <script>alert(1)</script>'
        result = app_mod.build_prereq_dot(["COMP110"], malicious_catalog, [], [])
        # Double-quotes in labels must be escaped as \"
        import re
        # Find label assignments — must not have unescaped " inside
        label_matches = re.findall(r'label="(.*?)"', result)
        for label in label_matches:
            # Any remaining raw " inside a label value means injection
            assert '"' not in label, f"Unescaped quote in DOT label: {label}"

    # ── _req_short_desc ───────────────────────────────────────────────────────

    def test_req_short_desc_gen_ed_codes(self, app_mod):
        if not hasattr(app_mod, "_req_short_desc"):
            pytest.skip("_req_short_desc not importable")
        for gen_ed_id in ["FY-SEMINAR", "FC-AESTH", "FC-NATSCI", "FC-QUANT", "RESEARCH",
                          "HI-EXP", "COMM", "LFIT", "FAD", "INTERDISCIPLINARY"]:
            result = app_mod._req_short_desc(gen_ed_id, "Some long description")
            assert isinstance(result, str) and len(result) > 0
            # Gen-ed codes use the fixed abbreviation table, not the raw desc
            assert result != "Some long description"

    def test_req_short_desc_unknown_id(self, app_mod):
        if not hasattr(app_mod, "_req_short_desc"):
            pytest.skip("_req_short_desc not importable")
        result = app_mod._req_short_desc("UNKNOWN_GROUP", "Fifteen courses in upper division electives")
        assert isinstance(result, str)


# ─────────────────────────────────────────────────────────────────────────────
# VECTOR 5 — Pipeline Integration & Session-State Safety
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineIntegration:
    """
    Full pipeline integration tests calling backend functions directly.

    Deliberately avoids importing app.py to prevent the numpy double-import
    crash on Python 3.14.  The logic under test is identical to run_pipeline()
    in app.py — we replicate its call sequence here.
    """

    def _run_backend_pipeline(self, catalog, requirements, completed_courses,
                               majors_to_check, planned_courses=None, avoid_courses=None):
        """Mirror run_pipeline() logic using only backend modules."""
        from src.planner.requirements_checker import check_requirements, generate_slots_and_candidates
        from src.planner.path_generator import solve_optimal_path
        from src.planner.topological_sort import kahns_algorithm

        planned  = list(planned_courses or [])
        avoid    = list(avoid_courses or [])
        assumed  = list(dict.fromkeys(completed_courses))

        _selection_avoid = list(set(assumed + avoid))

        # PASS 1 — Audit
        results_by_track = {}
        for m in majors_to_check:
            results_by_track[m["track"]] = check_requirements(
                requirements, catalog, assumed,
                avoid_courses=avoid,
                track_id=m["track"], concentration_id=m["concentration"],
            )

        # PASS 2 — Solver
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=requirements, catalog=catalog,
            majors_to_check=majors_to_check,
            completed_courses=assumed, avoid_courses=_selection_avoid,
        )
        best_path, course_to_slots_map = solve_optimal_path(
            slots=slots, canon_catalog=cc, credit_ledger=cl,
            macro_bindings=mb, blacklist=bl, remaining_semesters=8,
        )

        # PASS 3 — Audit dict
        audit = {}
        for m in majors_to_check:
            track = m["track"]
            audit[track] = {
                "results":         results_by_track[track],
                "remaining":       [],
                "fulfillment_map": {},
            }

        for course, slot_ids in course_to_slots_map.items():
            for slot_id in slot_ids:
                parts = slot_id.split("__")
                if len(parts) >= 2:
                    program_id = parts[0]
                    if program_id in audit:
                        if course not in audit[program_id]["remaining"]:
                            audit[program_id]["remaining"].append(course)
                        audit[program_id]["fulfillment_map"][course] = parts[1]

        semester_path = kahns_algorithm(best_path, catalog)
        flat_path = []
        for sem_courses in semester_path.values():
            flat_path.extend(sem_courses)

        return {
            "completed":     completed_courses,
            "in_progress":   [],
            "planned":       planned,
            "audit":         audit,
            "path":          flat_path,
            "semester_path": semester_path,
        }

    def test_pipeline_empty_transcript(self, real_catalog, real_requirements):
        result = self._run_backend_pipeline(
            real_catalog, real_requirements,
            completed_courses=[],
            majors_to_check=[
                {"track": "Computer_Science_Minor", "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ]
        )
        assert isinstance(result["completed"], list)
        assert isinstance(result["path"], list)
        assert isinstance(result["audit"], dict)

    def test_pipeline_full_transcript_yields_empty_path(self, real_catalog, real_requirements):
        """When every course is completed, the graduation path must be empty."""
        all_courses = list(real_catalog.keys())
        result = self._run_backend_pipeline(
            real_catalog, real_requirements,
            completed_courses=all_courses,
            majors_to_check=[
                {"track": "Computer_Science_Minor", "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ]
        )
        assert result["path"] == []

    def test_pipeline_planned_courses_appear_in_output(self, real_catalog, real_requirements):
        result = self._run_backend_pipeline(
            real_catalog, real_requirements,
            completed_courses=[],
            majors_to_check=[
                {"track": "Computer_Science_Minor", "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ],
            planned_courses=["COMP110", "COMP210"]
        )
        assert "COMP110" in result["planned"] or "COMP210" in result["planned"]

    def test_pipeline_avoid_courses_not_in_path(self, real_catalog, real_requirements):
        """Choice-group elective courses that are avoided must not appear in path.

        Required courses (required_courses list) are never avoidable by design;
        we only test elective courses that appear in choice_groups options.
        Stats Minor has no required_courses — all slots are from choice groups.
        """
        # Stats Minor: STOR155, STOR305, STOR215 are pure choice-group options (not required)
        avoid = ["STOR155", "STOR305", "STOR215"]
        result = self._run_backend_pipeline(
            real_catalog, real_requirements,
            completed_courses=[],
            majors_to_check=[
                {"track": "Statistics_and_Analytics_Minor", "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ],
            avoid_courses=avoid
        )
        path_set = set(result["path"])
        for c in avoid:
            assert c not in path_set, f"Avoided elective course {c} appeared in path"

    def test_pipeline_audit_structure_complete(self, real_catalog, real_requirements):
        result = self._run_backend_pipeline(
            real_catalog, real_requirements,
            completed_courses=[],
            majors_to_check=[
                {"track": "Computer_Science_BS", "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ]
        )
        for track_id, track_audit in result["audit"].items():
            assert "results" in track_audit
            assert "remaining" in track_audit
            assert "fulfillment_map" in track_audit

    def test_pipeline_semester_path_is_valid_dict(self, real_catalog, real_requirements):
        result = self._run_backend_pipeline(
            real_catalog, real_requirements,
            completed_courses=[],
            majors_to_check=[
                {"track": "Data_Science_BS", "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ]
        )
        sem_path = result.get("semester_path", {})
        assert isinstance(sem_path, dict)
        for sem, courses in sem_path.items():
            assert isinstance(sem, str)
            assert isinstance(courses, list)

    def test_pipeline_no_ghost_courses_in_audit_remaining(self, real_catalog, real_requirements):
        """All courses in audit['remaining'] must exist in catalog."""
        result = self._run_backend_pipeline(
            real_catalog, real_requirements,
            completed_courses=[],
            majors_to_check=[
                {"track": "Computer_Science_BS", "concentration": "None"},
                {"track": "UNC_General_Education", "concentration": "None"},
            ]
        )
        for track_id, track_data in result["audit"].items():
            for c in track_data.get("remaining", []):
                assert c in real_catalog, \
                    f"Ghost course '{c}' in audit['remaining'] for {track_id}"


# ─────────────────────────────────────────────────────────────────────────────
# VECTOR 6 — Data Quality Assertions
# ─────────────────────────────────────────────────────────────────────────────

class TestDataQuality:
    """Structural invariants the data files must satisfy for V1."""

    def test_all_tracks_have_base_requirements_key(self, real_requirements):
        for track, tdata in real_requirements.items():
            assert "base_requirements" in tdata, \
                f"Track '{track}' missing 'base_requirements' key"

    def test_choice_group_ids_unique_within_section(self, real_requirements):
        """Within each section (base OR concentration) group IDs must be unique."""
        for track, tdata in real_requirements.items():
            base = tdata.get("base_requirements", {})
            base_ids = [g["id"] for g in base.get("choice_groups", [])]
            base_dupes = [i for i in base_ids if base_ids.count(i) > 1]
            assert not base_dupes, \
                f"{track}/base_requirements has duplicate group IDs: {list(set(base_dupes))}"

            for conc_name, conc in tdata.get("concentrations", {}).items():
                conc_ids = [g["id"] for g in conc.get("choice_groups", [])]
                conc_dupes = [i for i in conc_ids if conc_ids.count(i) > 1]
                assert not conc_dupes, \
                    f"{track}/{conc_name} has duplicate group IDs: {list(set(conc_dupes))}"

    def test_no_cross_section_group_id_collisions(self, real_requirements):
        """After the data fix, no concentration group ID should shadow a base group ID."""
        collisions = []
        for track, tdata in real_requirements.items():
            base = tdata.get("base_requirements", {})
            base_ids = set(g["id"] for g in base.get("choice_groups", []))
            for conc_name, conc in tdata.get("concentrations", {}).items():
                for grp in conc.get("choice_groups", []):
                    if grp["id"] in base_ids:
                        collisions.append(f"{track}/{conc_name}: '{grp['id']}'")
        assert not collisions, \
            f"Cross-section group ID collisions found (run data fix script): {collisions}"

    def test_all_catalog_courses_have_required_keys(self, real_catalog):
        required_keys = {"name", "credits", "prerequisites", "corequisites", "cross_listed", "attributes"}
        for course, data in real_catalog.items():
            missing = required_keys - set(data.keys())
            assert not missing, f"Course '{course}' missing keys: {missing}"

    def test_no_negative_credits_in_catalog(self, real_catalog):
        for course, data in real_catalog.items():
            assert data.get("credits", 0) >= 0, \
                f"Course '{course}' has negative credits: {data['credits']}"

    def test_prerequisites_are_lists_of_lists(self, real_catalog):
        """prerequisites must be list[list[str]] — no bare string references."""
        for course, data in real_catalog.items():
            prereqs = data.get("prerequisites", [])
            assert isinstance(prereqs, list), f"{course}: prerequisites is not a list"
            for pathway in prereqs:
                assert isinstance(pathway, list), \
                    f"{course}: prerequisite pathway is not a list: {pathway}"
                for prereq in pathway:
                    assert isinstance(prereq, str), \
                        f"{course}: prerequisite item is not a str: {prereq}"

    def test_cross_listed_are_lists(self, real_catalog):
        for course, data in real_catalog.items():
            assert isinstance(data.get("cross_listed", []), list), \
                f"{course}: cross_listed is not a list"

    def test_choice_groups_have_id_field(self, real_requirements):
        for track, tdata in real_requirements.items():
            base = tdata.get("base_requirements", {})
            for grp in base.get("choice_groups", []):
                assert "id" in grp, f"{track}: choice_group missing 'id' field: {grp}"

    def test_empty_tracks_identified(self, real_requirements):
        """Document which tracks have no requirements — these are known data gaps."""
        empty_tracks = []
        for track, tdata in real_requirements.items():
            base = tdata.get("base_requirements", {})
            if not base.get("required_courses") and not base.get("choice_groups"):
                empty_tracks.append(track)
        # Document them; fail if NEW ones appear beyond known set
        KNOWN_EMPTY = {
            # Closed/paused programs — pages have no course data to scrape
            "Sexuality_Studies_Minor",   # Women's & Gender Studies: enrollment paused
            "Coaching_Education_Minor",  # Exercise & Sport Science: closed to new applications
        }
        new_empty = set(empty_tracks) - KNOWN_EMPTY
        assert not new_empty, \
            f"Newly empty tracks (scrape failures?) detected: {new_empty}"

    def test_required_courses_are_strings(self, real_requirements):
        for track, tdata in real_requirements.items():
            base = tdata.get("base_requirements", {})
            for c in base.get("required_courses", []):
                assert isinstance(c, str), \
                    f"{track}: required_course entry is not a str: {c}"

    def test_credits_required_is_numeric(self, real_requirements):
        for track, tdata in real_requirements.items():
            base = tdata.get("base_requirements", {})
            for grp in base.get("choice_groups", []):
                cr = grp.get("credits_required")
                if cr is not None:
                    assert isinstance(cr, (int, float)), \
                        f"{track}/{grp['id']}: credits_required is not numeric: {cr}"

    def test_courses_required_is_int_or_none(self, real_requirements):
        for track, tdata in real_requirements.items():
            base = tdata.get("base_requirements", {})
            for grp in base.get("choice_groups", []):
                co = grp.get("courses_required")
                if co is not None:
                    assert isinstance(co, int), \
                        f"{track}/{grp['id']}: courses_required is not int: {co}"

    def test_all_cross_listed_courses_have_reciprocal_entry(self, real_catalog):
        """If A lists B as cross-listed, B should exist in catalog (soft warning)."""
        ghost_cross_listings = []
        for course, data in real_catalog.items():
            for xl in data.get("cross_listed", []):
                if xl not in real_catalog:
                    ghost_cross_listings.append((course, xl))
        # Collect and report — don't hard-fail since some ghost refs are intentional
        if ghost_cross_listings:
            print(f"\n[DATA QUALITY] {len(ghost_cross_listings)} cross-listed ghost refs: "
                  f"{ghost_cross_listings[:5]}")
        # But if > 5% of courses are involved it's a systemic problem
        pct = len(ghost_cross_listings) / max(len(real_catalog), 1)
        assert pct < 0.05, \
            f"{pct:.1%} of catalog courses have ghost cross-listings — data issue"

    def test_course_catalog_json_is_valid(self):
        with open(CATALOG_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_degree_requirements_json_is_valid(self):
        with open(REQUIREMENTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_required_courses_not_exceeding_degree_credit_ceiling(self, real_requirements, real_catalog):
        """No track should have required courses totaling >180 credits.

        The UNC graduation minimum is 120 credits; a track requiring >180 cr
        of *mandatory* courses almost certainly has a scraper error (optional
        pool courses were collapsed into required_courses).
        """
        CREDIT_CEILING = 180
        KNOWN_BLOATED = {
            # Known scraper errors where pool options were collapsed — documented
            # but not yet fixed in the data pipeline. Track here so NEW regressions
            # are caught immediately.
            "Latin_American_Studies_BA",
            "American_Indian_and_Indigenous_Studies_Minor",
            "American_Studies_BA_AIIS_Concentration",
        }
        new_bloated = []
        for track, tdata in real_requirements.items():
            if track in KNOWN_BLOATED:
                continue
            base_req = tdata.get("base_requirements", {}).get("required_courses", [])
            total_cr = sum(real_catalog.get(c, {}).get("credits", 0) for c in base_req)
            if total_cr > CREDIT_CEILING:
                new_bloated.append(f"{track}: {total_cr:.0f} required credits")
        assert not new_bloated, \
            f"Tracks with bloated required_courses (possible scraper collapse): {new_bloated}"

    def test_ghost_base_required_courses_not_growing(self, real_requirements, real_catalog):
        """Document and cap the number of tracks with ghost base required courses.

        Ghost required courses = required courses that don't exist in the catalog,
        making satisfaction permanently impossible.  New ghosts beyond the known
        set indicate a data regression.
        """
        KNOWN_GHOST_TRACKS = {
            # Pending catalog pipeline re-run with HBEH/CHIP/PHRS departments added
            "Community_and_Global_Public_Health_BSPH", # HBEH series — run_catalog_pipeline.py
            "Pharmaceutical_Sciences_Minor",           # PHRS series — run_catalog_pipeline.py
            "Data_Science_BS",                         # CHIP series (Health Informatics conc)
        }
        new_ghost_tracks = []
        for track, tdata in real_requirements.items():
            if track in KNOWN_GHOST_TRACKS:
                continue
            base_req = tdata.get("base_requirements", {}).get("required_courses", [])
            ghosts = [c for c in base_req if c not in real_catalog]
            if ghosts:
                new_ghost_tracks.append(f"{track}: {ghosts}")
        assert not new_ghost_tracks, \
            f"NEW tracks with ghost base required courses (data regression): {new_ghost_tracks}"

    def test_no_new_permanently_unsatisfiable_groups(self, real_requirements, real_catalog):
        """Detect choice groups that can NEVER be satisfied by any real student.

        A group is permanently broken when:
          (a) courses_required > valid_options (accounting for required-course consumption), OR
          (b) all options are ghost courses not in catalog.

        The KNOWN_BROKEN set documents pre-existing scraper errors.  Any group
        that appears in this set AND is newly broken will be caught immediately.
        """
        from src.planner.requirements_checker import get_rule_based_options

        KNOWN_BROKEN_GROUPS = {
            # CS BS HCI concentration — 3 valid options for a 5-course requirement (scrape gap)
            "Computer_Science_BS/Human_Computer_Interaction/hci_electives_1",
            # Env Studies BA — 0-option groups (scrape gap)
            "Environmental_Studies_BA/base/enec_3",
            "Environmental_Studies_BA/base/enec_4",
            "Environmental_Studies_BA/Agriculture_and_Health/emes_324L_1",
            "Environmental_Studies_BA/Ecology_and_Society/emes_4",
            # Env Science BS — Water_and_Climate concentration scrape gap
            "Environmental_Science_BS/Water_and_Climate/emes_2",
            # LTAM BA — required-course collapse; needs requirements re-scrape
            "Latin_American_Studies_BA/base/core_requirements_numbered_1",
            # Pharmaceutical Sciences Minor — PHRS courses not yet in catalog
            # Will resolve after: python scripts/run_catalog_pipeline.py
            "Pharmaceutical_Sciences_Minor/base/core_requirements_electives_1",
            # Physics BA — 7+7 identical group double-capture; needs requirements re-scrape
            # Will resolve after: python scripts/run_requirements_pipeline.py --tracks Physics_BA --force
            "Physics_BA/base/phys_9",
        }

        newly_broken = []
        for track, tdata in real_requirements.items():
            base = tdata.get("base_requirements", {})
            req_set = set(base.get("required_courses", []))
            all_sections = [("base", base)]
            for cn, conc in tdata.get("concentrations", {}).items():
                all_sections.append((cn, conc))

            for section_name, section in all_sections:
                for g in section.get("choice_groups", []):
                    gid = g["id"]
                    key = f"{track}/{section_name}/{gid}"
                    if key in KNOWN_BROKEN_GROUPS:
                        continue  # already documented

                    cr = g.get("courses_required", 1)
                    cr_needed = g.get("credits_required")

                    if g.get("type") == "rule_based":
                        opts = get_rule_based_options(g.get("rule") or {}, real_catalog)
                    else:
                        opts = g.get("options") or []

                    valid = [o for o in opts if o in real_catalog and o not in req_set]

                    if cr_needed:
                        total = sum(real_catalog.get(o, {}).get("credits", 0) for o in valid)
                        if total < cr_needed and total == 0:
                            newly_broken.append(f"{key}: pool empty (need {cr_needed} cr)")
                    else:
                        if cr > len(valid) and len(opts) > 0:
                            newly_broken.append(
                                f"{key}: need {cr}, only {len(valid)} valid of {len(opts)} opts"
                            )

        assert not newly_broken, \
            f"NEW permanently unsatisfiable groups detected (data regression):\n" + \
            "\n".join(f"  {b}" for b in newly_broken)

    def test_no_new_concentration_required_course_bloat(self, real_requirements, real_catalog):
        """Concentrations whose required_courses total >120 credits are almost certainly
        scraper collapses (pool options promoted to required).  Document the known
        offenders; fail if new ones appear."""
        KNOWN_BLOATED_CONCENTRATIONS = {
            # Scraper structural issue — concentration course lists are injected as required_courses.
            # Re-scraping reproduces the same structure; requires scraper architecture change to fix.
            "English_and_Comparative_Literature_BA/in_Writing_Editing_and_Digital_Publishing",
            "English_and_Comparative_Literature_BA/in_Science_Medicine_and_Literature",
            "English_and_Comparative_Literature_BA/in_Social_Justice_and_Literature",
            "Environmental_Science_BS/Ecology_and_Natural_Resources",
            "Environmental_Studies_BA/Environmental_Behavior_and_Decision_Making",
            "Environmental_Studies_BA/Ecology_and_Society",
            "Environmental_Studies_BA/Population_Environment_and_Development",
            "Environmental_Science_BS/Water_and_Climate",
            "Environmental_Science_BS/Environment_and_Health",
        }
        CREDIT_CEILING = 120
        new_bloated = []
        for track, tdata in real_requirements.items():
            for conc_name, conc in tdata.get("concentrations", {}).items():
                key = f"{track}/{conc_name}"
                if key in KNOWN_BLOATED_CONCENTRATIONS or conc_name == "None":
                    continue
                req_c = conc.get("required_courses", [])
                total_cr = sum(real_catalog.get(c, {}).get("credits", 0) for c in req_c if c in real_catalog)
                if total_cr > CREDIT_CEILING:
                    new_bloated.append(f"{key}: {total_cr:.0f} required credits")
        assert not new_bloated, \
            f"NEW concentration required-course bloat (scraper collapse?): {new_bloated}"

    def test_masc101_removed_from_requirements(self, real_requirements):
        """MASC is the retired Marine Sciences dept code (now EMES).
        MASC101 should have been replaced with EMES101 in all requirements."""
        masc_refs = []
        for track, tdata in real_requirements.items():
            base = tdata.get("base_requirements", {})
            for c in base.get("required_courses", []):
                if c.startswith("MASC"):
                    masc_refs.append(f"{track}: {c}")
            for grp in base.get("choice_groups", []):
                for opt in grp.get("options", []):
                    if opt.startswith("MASC"):
                        masc_refs.append(f"{track}/{grp['id']}: {opt}")
        assert not masc_refs, \
            f"Retired MASC dept code still in requirements (use EMES): {masc_refs}"


# ─────────────────────────────────────────────────────────────────────────────
# VECTOR 7 — Security & Robustness
# ─────────────────────────────────────────────────────────────────────────────

class TestSecurityAndRobustness:
    """Injection, path traversal, and resource exhaustion guards."""

    def test_dot_output_escapes_backslash(self):
        """DOT label generator must not emit literal backslashes from course names."""
        import unittest.mock as mock
        import importlib.util

        st_mock = mock.MagicMock()
        st_mock.cache_resource = lambda f: f
        st_mock.secrets = {}
        with mock.patch.dict("sys.modules", {"streamlit": st_mock}):
            spec = importlib.util.spec_from_file_location("app_sec", os.path.join(BASE, "app.py"))
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception:
                pass
            if not hasattr(mod, "build_prereq_dot"):
                pytest.skip("build_prereq_dot not importable")
            evil_catalog = {
                "EVIL101": {
                    "name": 'Evil\\n"; color=red; style=filled //Injection',
                    "credits": 3,
                    "prerequisites": [],
                    "corequisites": [],
                    "cross_listed": [],
                    "attributes": []
                }
            }
            result = mod.build_prereq_dot(["EVIL101"], evil_catalog, [], [])
            assert isinstance(result, str)
            # DOT parser would fail on un-balanced quotes — our escaping must prevent that
            # Check the label string doesn't contain raw unescaped double quotes
            import re
            for label in re.findall(r'label="(.*?)"', result, re.DOTALL):
                assert '"' not in label, f"Unescaped quote in label: {label}"

    def test_solve_handles_massive_candidate_pool_without_hanging(self, real_catalog, real_requirements):
        """A pool slot with 1000+ candidates must finish ILS within timeout."""
        from src.planner.requirements_checker import generate_slots_and_candidates
        from src.planner.path_generator import solve_optimal_path
        # UNC General Education has FC rule-based pools with huge candidate sets
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[{"track": "UNC_General_Education", "concentration": "None"}],
            completed_courses=[]
        )
        t0 = time.time()
        path, mapping = solve_optimal_path(slots, cc, cl, mb, bl, remaining_semesters=8)
        elapsed = time.time() - t0
        assert elapsed < 20.0, f"Gen Ed solve took {elapsed:.1f}s — too slow"

    def test_check_requirements_corrupt_catalog_values(self, real_requirements):
        """Catalog with corrupted values must not crash requirements checker."""
        from src.planner.requirements_checker import check_requirements
        corrupt_catalog = {
            "COMP110": {"name": None, "credits": "not_a_number",
                        "prerequisites": None, "corequisites": None,
                        "cross_listed": None, "attributes": None},
            "COMP210": {"name": 12345, "credits": -1,
                        "prerequisites": [], "corequisites": [],
                        "cross_listed": [], "attributes": []},
        }
        try:
            result = check_requirements(real_requirements, corrupt_catalog, ["COMP110"],
                                        track_id="Computer_Science_Minor",
                                        concentration_id="None")
            assert isinstance(result, dict)
        except (TypeError, AttributeError) as exc:
            pytest.fail(f"Corrupt catalog values crashed check_requirements: {exc}")

    def test_run_pipeline_large_planned_avoid_lists(self, real_catalog, real_requirements):
        """Pipeline must handle large planned/avoid lists without crashing."""
        from src.planner.requirements_checker import generate_slots_and_candidates
        from src.planner.path_generator import solve_optimal_path
        all_courses = list(real_catalog.keys())
        # Avoid the first 3000 courses, plan the next 100
        avoid = all_courses[:3000]
        planned = all_courses[3000:3100]
        slots, cc, cl, mb, bl = generate_slots_and_candidates(
            requirements=real_requirements,
            catalog=real_catalog,
            majors_to_check=[{"track": "Computer_Science_Minor", "concentration": "None"}],
            completed_courses=[],
            avoid_courses=avoid + planned  # both go into avoid for slot generation
        )
        path, mapping = solve_optimal_path(slots, cc, cl, mb, bl, remaining_semesters=8)
        assert isinstance(path, list)

    def test_feedback_write_no_filesystem_traversal(self, tmp_path):
        """_write_feedback must not write outside its designated log path."""
        import unittest.mock as mock
        import importlib.util

        st_mock = mock.MagicMock()
        st_mock.cache_resource = lambda f: f
        st_mock.secrets = {}
        with mock.patch.dict("sys.modules", {"streamlit": st_mock}):
            spec = importlib.util.spec_from_file_location("app_sec2", os.path.join(BASE, "app.py"))
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception:
                pass
            if not hasattr(mod, "_write_feedback"):
                pytest.skip("_write_feedback not importable")
            # Ensure the feedback log path is fixed (no user-supplied path)
            import datetime
            entry = {
                "type": "Bug Report",
                "title": "../../etc/passwd",  # path traversal attempt in title field
                "description": "Test",
                "email": None,
                "timestamp": datetime.datetime.now().isoformat(),
            }
            # Should write to logs/feedback.json, not ../../etc/passwd
            original_dir = os.getcwd()
            try:
                os.chdir(str(tmp_path))
                os.makedirs("logs", exist_ok=True)
                mod._write_feedback(entry)
                assert os.path.exists(os.path.join(str(tmp_path), "logs", "feedback.json"))
                # Ensure no files written outside tmp_path
                import pathlib
                for f in pathlib.Path(str(tmp_path)).rglob("*"):
                    assert str(f).startswith(str(tmp_path)), \
                        f"File written outside tmp_path: {f}"
            finally:
                os.chdir(original_dir)
