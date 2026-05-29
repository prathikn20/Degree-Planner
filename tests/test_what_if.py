import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.planner.requirements_checker import check_requirements

CATALOG = {
    "STOR120": {"name": "Chance and Data", "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": []},
    "COMP110": {"name": "Intro to Programming", "credits": 3, "prerequisites": [], "cross_listed": [], "attributes": []},
}

REQUIREMENTS = {
    "TEST_BS": {
        "base_requirements": {
            "required_courses": [],
            "choice_groups": [
                {
                    "id": "stats_or_comp",
                    "type": "options",
                    "options": ["STOR120", "COMP110"],
                    "courses_required": 1,
                    "is_core": True,
                }
            ]
        },
        "concentrations": {
            "None": {"required_courses": [], "choice_groups": []}
        }
    }
}


def test_planned_course_satisfies_group():
    """Test Case A: planned COMP110 in assumed_completed should satisfy the group."""
    assumed_completed = ["COMP110"]
    results = check_requirements(
        REQUIREMENTS, CATALOG, assumed_completed,
        track_id="TEST_BS", concentration_id="None"
    )
    assert "stats_or_comp" in results["satisfied"], (
        f"Expected 'stats_or_comp' in satisfied, got satisfied={results['satisfied']}"
    )
    assert "stats_or_comp" not in results["unsatisfied"], (
        f"'stats_or_comp' should not be in unsatisfied"
    )
    print("Test Case A PASSED: planned COMP110 satisfies 'stats_or_comp' group")


def test_avoid_course_removed_from_options():
    """Test Case B: avoid STOR120 → group unsatisfied AND STOR120 not in options."""
    assumed_completed = []
    avoid_courses = ["STOR120"]
    results = check_requirements(
        REQUIREMENTS, CATALOG, assumed_completed,
        avoid_courses=avoid_courses,
        track_id="TEST_BS", concentration_id="None"
    )
    assert "stats_or_comp" in results["unsatisfied"], (
        f"Expected 'stats_or_comp' in unsatisfied, got unsatisfied={results['unsatisfied']}"
    )
    options = results["missing_courses"].get("stats_or_comp", {}).get("options", [])
    assert "STOR120" not in options, (
        f"Expected STOR120 to be absent from options, but got options={options}"
    )
    print(f"Test Case B PASSED: group unsatisfied and STOR120 not in options={options}")


if __name__ == "__main__":
    test_planned_course_satisfies_group()
    test_avoid_course_removed_from_options()
    print("\nAll tests passed.")
