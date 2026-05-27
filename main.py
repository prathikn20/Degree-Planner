from planner.graph import load_catalog, load_requirements, build_graph
from planner.requirements_checker import check_requirements
from planner.path_generator import get_remaining_courses, kahns_algorithm

COMPLETED = [
    "COMP110", "COMP210",
    "MATH231", "MATH232", "MATH235", "MATH381",
    "DATA110", "ENGL105", "ENEC202", "POLI130",
    "AAAD231", "HIST126", "CMPL55", "IDST111L", "IDST101", "ASTR103"
]

IN_PROGRESS = ["COMP211", "COMP301", "DATA215", "MATH347", "BUSI100"]

def print_requirement_status(results):
    print("=" * 50)
    print("REQUIREMENT STATUS")
    print("=" * 50)
    print("\nSATISFIED:")
    for req in results["satisfied"]:
        print(f"  + {req}")
    print("\nUNSATISFIED:")
    for req_id, details in results["missing_courses"].items():
        if isinstance(details, list):
            print(f"  - {req_id}")
        else:
            print(f"  - {req_id}: need {details['still_needed']} more")
            print(f"    options: {details['options']}")

def print_path(path, catalog):
    print("\n" + "=" * 50)
    print("SUGGESTED PATH TO GRADUATION")
    print("=" * 50)
    for i, course in enumerate(path, 1):
        name = catalog.get(course, {}).get("name", "Unknown")
        credits = catalog.get(course, {}).get("credits", "?")
        print(f"  {i:2}. {course} - {name} ({credits} cr)")

    total = sum(catalog.get(c, {}).get("credits", 0) for c in path)
    print(f"\n  Total remaining credits in path: {total}")

def main():
    catalog = load_catalog("data/course_catalog.json")
    requirements = load_requirements("data/degree_requirements.json")
    graph = build_graph(catalog)

    results = check_requirements(requirements, catalog, COMPLETED)
    print_requirement_status(results)

    remaining = get_remaining_courses(results, requirements, catalog, COMPLETED)

    print("\nIN PROGRESS (not counted as complete):")
    for c in IN_PROGRESS:
        print(f"  ~ {c}")

    path = kahns_algorithm(graph, catalog, COMPLETED, remaining)
    print_path(path, catalog)

if __name__ == "__main__":
    main()