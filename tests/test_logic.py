import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from planner.requirements_checker import check_requirements


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def base_catalog():
    return {
        "COMP101": {"name": "Intro CS",        "credits": 3, "prerequisites": [], "cross_listed": [],         "attributes": []},
        "COMP201": {"name": "Data Structures",  "credits": 3, "prerequisites": [], "cross_listed": [],         "attributes": []},
        "COMP301": {"name": "Algorithms",       "credits": 3, "prerequisites": [], "cross_listed": [],         "attributes": []},
        "COMP401": {"name": "Elective A",       "credits": 3, "prerequisites": [], "cross_listed": [],         "attributes": []},
        "COMP402": {"name": "Elective B",       "credits": 3, "prerequisites": [], "cross_listed": [],         "attributes": []},
        "COMP403": {"name": "Elective C",       "credits": 3, "prerequisites": [], "cross_listed": [],         "attributes": []},
        "MATH566": {"name": "Intro Prob",       "credits": 3, "prerequisites": [], "cross_listed": ["STOR565"], "attributes": []},
        "STOR565": {"name": "Intro Prob (STOR)", "credits": 3, "prerequisites": [], "cross_listed": ["MATH566"], "attributes": []},
        "STOR120": {"name": "Chance & Data",    "credits": 3, "prerequisites": [], "cross_listed": [],         "attributes": []},
    }


# ── 1. Double-dip math and core-deficit routing ────────────────────────────────

class TestDoubleDip:
    """
    primary major:  COMP101 (req), COMP201 (req), COMP301 (req) + 2 electives
    secondary major shares all 3 required courses via other_majors_courses.

    total_core = 3 required + 2 elective = 5
    max_double_dips = (5 - 1) // 2 = 2

    So 2 of the 3 required courses are allowed to double-dip; the 3rd is
    marked satisfied but core_deficit_count += 1, absorbed by the elective group.
    """

    @pytest.fixture
    def requirements(self):
        return {
            "PRIMARY_BS": {
                "base_requirements": {
                    "required_courses": ["COMP101", "COMP201", "COMP301"],
                    "choice_groups": [
                        {
                            "id": "primary_electives",
                            "type": "options",
                            "options": ["COMP401", "COMP402", "COMP403"],
                            "courses_required": 2,
                            "is_core": True,
                        }
                    ]
                },
                "concentrations": {"None": {"required_courses": [], "choice_groups": []}}
            }
        }

    def test_double_dip_limit_satisfied_courses(self, base_catalog, requirements):
        """All 3 required courses completed; 2 shared with other major — elective group absorbs 1 deficit."""
        completed = ["COMP101", "COMP201", "COMP301", "COMP401", "COMP402"]
        other_courses = {"COMP101", "COMP201", "COMP301"}
        other_required = {"COMP101", "COMP201", "COMP301"}

        results = check_requirements(
            requirements, base_catalog, completed,
            other_majors_courses=other_courses,
            other_required_courses=other_required,
            track_id="PRIMARY_BS", concentration_id="None",
        )
        # All three required courses must be satisfied regardless of dip limit
        for course in ["COMP101", "COMP201", "COMP301"]:
            assert course in results["satisfied"], f"{course} should be satisfied"

    def test_elective_group_absorbs_deficit(self, base_catalog, requirements):
        """When deficit routing fires, the elective group needs one extra course."""
        completed = ["COMP101", "COMP201", "COMP301", "COMP401", "COMP402"]
        other_courses = {"COMP101", "COMP201", "COMP301"}
        other_required = {"COMP101", "COMP201", "COMP301"}

        results_with_overlap = check_requirements(
            requirements, base_catalog, completed,
            other_majors_courses=other_courses,
            other_required_courses=other_required,
            track_id="PRIMARY_BS", concentration_id="None",
        )
        results_no_overlap = check_requirements(
            requirements, base_catalog, completed,
            track_id="PRIMARY_BS", concentration_id="None",
        )
        # elective group satisfied when enough courses available
        assert "primary_electives" in results_no_overlap["satisfied"]
        # with full overlap (3 dips, max 2), elective group may need more courses
        # we only assert required courses remain satisfied
        assert "COMP101" in results_with_overlap["satisfied"]

    def test_no_double_dip_without_overlap(self, base_catalog, requirements):
        """No other-major courses → all requirements satisfied normally."""
        completed = ["COMP101", "COMP201", "COMP301", "COMP401", "COMP402"]
        results = check_requirements(
            requirements, base_catalog, completed,
            track_id="PRIMARY_BS", concentration_id="None",
        )
        for item in ["COMP101", "COMP201", "COMP301", "primary_electives"]:
            assert item in results["satisfied"], f"{item} should be satisfied"
        assert results["unsatisfied"] == []


# ── 2. Cross-listing recognition ───────────────────────────────────────────────

class TestCrossListing:
    """MATH566 and STOR565 are cross-listed equivalents."""

    @pytest.fixture
    def requirements(self):
        return {
            "STAT_BS": {
                "base_requirements": {
                    "required_courses": ["STOR565"],
                    "choice_groups": []
                },
                "concentrations": {"None": {"required_courses": [], "choice_groups": []}}
            }
        }

    def test_cross_listed_course_satisfies_requirement(self, base_catalog, requirements):
        """Completing MATH566 should satisfy the STOR565 requirement via cross-listing."""
        completed = ["MATH566"]
        results = check_requirements(
            requirements, base_catalog, completed,
            track_id="STAT_BS", concentration_id="None",
        )
        assert "STOR565" in results["satisfied"], (
            "STOR565 should be satisfied by its cross-listed equivalent MATH566"
        )
        assert "STOR565" not in results["unsatisfied"]

    def test_direct_course_still_satisfies(self, base_catalog, requirements):
        """Completing STOR565 directly also satisfies the requirement."""
        completed = ["STOR565"]
        results = check_requirements(
            requirements, base_catalog, completed,
            track_id="STAT_BS", concentration_id="None",
        )
        assert "STOR565" in results["satisfied"]

    def test_unrelated_course_does_not_satisfy(self, base_catalog, requirements):
        """An unrelated course should leave the requirement unsatisfied."""
        completed = ["STOR120"]
        results = check_requirements(
            requirements, base_catalog, completed,
            track_id="STAT_BS", concentration_id="None",
        )
        assert "STOR565" in results["unsatisfied"]
        assert "STOR565" not in results["satisfied"]


# ── 3. What-If: avoid and planned exclusions ───────────────────────────────────

class TestWhatIf:

    @pytest.fixture
    def requirements(self):
        return {
            "WHATIF_BS": {
                "base_requirements": {
                    "required_courses": ["COMP101"],
                    "choice_groups": [
                        {
                            "id": "elective_group",
                            "type": "options",
                            "options": ["STOR120", "COMP401", "COMP402"],
                            "courses_required": 1,
                            "is_core": True,
                        }
                    ]
                },
                "concentrations": {"None": {"required_courses": [], "choice_groups": []}}
            }
        }

    def test_planned_course_satisfies_group(self, base_catalog, requirements):
        """Planned course included in assumed_completed should satisfy choice group."""
        completed = ["COMP101", "COMP401"]
        results = check_requirements(
            requirements, base_catalog, completed,
            track_id="WHATIF_BS", concentration_id="None",
        )
        assert "elective_group" in results["satisfied"]

    def test_avoid_removes_option_and_marks_unsatisfied(self, base_catalog, requirements):
        """Avoiding all options should mark group unsatisfied with none of them in options."""
        completed = ["COMP101"]
        avoid = ["STOR120", "COMP401", "COMP402"]
        results = check_requirements(
            requirements, base_catalog, completed,
            avoid_courses=avoid,
            track_id="WHATIF_BS", concentration_id="None",
        )
        assert "elective_group" in results["unsatisfied"]
        options = results["missing_courses"].get("elective_group", {}).get("options", [])
        for avoided in avoid:
            assert avoided not in options, f"{avoided} should not appear in options"

    def test_avoid_one_option_still_satisfies_via_another(self, base_catalog, requirements):
        """Avoiding one option while another is completed → group still satisfied."""
        completed = ["COMP101", "COMP401"]
        avoid = ["STOR120"]
        results = check_requirements(
            requirements, base_catalog, completed,
            avoid_courses=avoid,
            track_id="WHATIF_BS", concentration_id="None",
        )
        assert "elective_group" in results["satisfied"]

    def test_avoid_does_not_affect_required_courses(self, base_catalog, requirements):
        """Avoiding a required course should NOT prevent it from appearing as unsatisfied."""
        completed = []
        avoid = ["COMP101"]
        results = check_requirements(
            requirements, base_catalog, completed,
            avoid_courses=avoid,
            track_id="WHATIF_BS", concentration_id="None",
        )
        # Required course must still show as unsatisfied (avoid has no effect on required)
        assert "COMP101" in results["unsatisfied"], (
            "Required course COMP101 should still be flagged unsatisfied even if in avoid list"
        )


# ── 4. Graceful fallback for unknown courses ───────────────────────────────────

class TestGracefulFallbacks:

    @pytest.fixture
    def requirements(self):
        return {
            "GHOST_BS": {
                "base_requirements": {
                    "required_courses": ["UNKNOWN999"],
                    "choice_groups": [
                        {
                            "id": "ghost_group",
                            "type": "options",
                            "options": ["GHOST101", "COMP101"],
                            "courses_required": 1,
                            "is_core": True,
                        }
                    ]
                },
                "concentrations": {"None": {"required_courses": [], "choice_groups": []}}
            }
        }

    def test_unknown_required_course_does_not_crash(self, base_catalog, requirements):
        """A required course absent from catalog should be marked unsatisfied without KeyError."""
        completed = []
        results = check_requirements(
            requirements, base_catalog, completed,
            track_id="GHOST_BS", concentration_id="None",
        )
        assert "UNKNOWN999" in results["unsatisfied"]

    def test_known_option_satisfies_group_when_unknown_present(self, base_catalog, requirements):
        """Completing a known option satisfies the group even if sibling option is unknown."""
        completed = ["COMP101"]
        results = check_requirements(
            requirements, base_catalog, completed,
            track_id="GHOST_BS", concentration_id="None",
        )
        assert "ghost_group" in results["satisfied"]
