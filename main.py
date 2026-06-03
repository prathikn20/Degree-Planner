# UNUSED: Stale dev CLI demo. Imports get_remaining_courses and kahns_algorithm from
# path_generator (neither exists there) and tracker_parser (now transcript_parser).
# Not part of the Streamlit app.
import argparse

from src.planner.graph import load_catalog, load_requirements, build_graph
from src.planner.requirements_checker import check_requirements
from src.planner.path_generator import get_remaining_courses, kahns_algorithm
from src.planner.transcript_parser import parse_tarheel_tracker

_COMPLETED = [
    "COMP110", "COMP210",
    "MATH231", "MATH232", "MATH235", "MATH381",
    "DATA110", "ENGL105", "ENEC202", "POLI130",
    "AAAD231", "HIST126", "CMPL55", "IDST111L", "IDST101", "ASTR103"
]
_IN_PROGRESS = ["COMP211", "COMP301", "DATA215", "MATH347", "BUSI100"]
_PLANNED_COURSES = ["COMP421", "STOR435"]

def print_requirement_status(results, title):
    print("\n" + "=" * 50)
    print(f"REQUIREMENT STATUS: {title}")
    print("=" * 50)
    print("\nSATISFIED:")
    for req in results["satisfied"]:
        print(f"  + {req}")
    print("\nUNSATISFIED:")
    for req_id, details in results["missing_courses"].items():
        if isinstance(details, list):
            print(f"  - {req_id}")
        else:
            needed = details.get('still_needed') or details.get('credits_still_needed')
            suffix = "credits" if 'credits_still_needed' in details else "courses"
            print(f"  - {req_id}: need {needed} more {suffix}")

def print_path(path, catalog):
    print("\n" + "=" * 50)
    print("SUGGESTED PATH TO GRADUATION (DUAL DEGREE)")
    print("=" * 50)
    for i, course in enumerate(path, 1):
        name = catalog.get(course, {}).get("name", "Unknown")
        credits = catalog.get(course, {}).get("credits", "?")
        print(f"  {i:2}. {course} - {name} ({credits} cr)")

    total = sum(catalog.get(c, {}).get("credits", 0) for c in path)
    print(f"\n  Total remaining credits in path: {total}")

def main():
    parser = argparse.ArgumentParser(description="UNC Degree Planner")
    parser.add_argument("--tracker", metavar="PDF", help="Path to Tar Heel Tracker PDF")
    args = parser.parse_args()

    if args.tracker:
        parsed = parse_tarheel_tracker(args.tracker)
        completed = parsed["completed"]
        in_progress = parsed["in_progress"]
        planned = []
        print(f"Loaded {len(completed)} completed and {len(in_progress)} in-progress courses from {args.tracker}")
    else:
        completed = _COMPLETED
        in_progress = _IN_PROGRESS
        planned = _PLANNED_COURSES

    assumed_completed = completed + in_progress + planned

    catalog = load_catalog("data/course_catalog.json")
    requirements = load_requirements("data/degree_requirements.json")
    graph = build_graph(catalog)

    majors_to_check = [
        {"track": "Data_Science_BS", "concentration": "None"},
        {"track": "Computer_Science_BS", "concentration": "None"}
    ]

    baseline_courses = {}
    for program in majors_to_check:
        track = program["track"]
        conc = program["concentration"]
        res = check_requirements(
            requirements, catalog, assumed_completed,
            other_majors_courses=set(),
            track_id=track, concentration_id=conc
        )
        baseline_courses[track] = res.get("courses_used", set())

    all_remaining_courses = set()

    for program in majors_to_check:
        track = program["track"]
        conc = program["concentration"]

        other_majors_pool = set()
        other_required = set()
        for other_track, courses in baseline_courses.items():
            if other_track != track:
                other_majors_pool.update(courses)
                other_base = requirements.get(other_track, {}).get("base_requirements", {})
                other_required.update(other_base.get("required_courses", []))

        results = check_requirements(
            requirements, catalog, assumed_completed,
            other_majors_courses=other_majors_pool,
            other_required_courses=other_required,
            track_id=track, concentration_id=conc
        )
        print_requirement_status(results, f"{track} (Concentration: {conc})")

        remaining, _ = get_remaining_courses(
            results, requirements, catalog, assumed_completed,
            track_id=track, concentration_id=conc
        )
        all_remaining_courses.update(remaining)

    if planned:
        print("\nSIMULATING WITH FUTURE CLASSES:")
        for c in planned:
            print(f"  * {c}")

    path = kahns_algorithm(graph, catalog, assumed_completed, list(all_remaining_courses))
    print_path(path, catalog)

if __name__ == "__main__":
    main()