import json
from collections import deque


def load_catalog(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)


def load_requirements(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)


def build_graph(catalog):
    graph = {course: [] for course in catalog}

    for course, data in catalog.items():
        for prereq_group in data['prerequisites']:
            for prereq in prereq_group:
                if prereq in graph:
                    if course not in graph[prereq]:
                        graph[prereq].append(course)

    return graph


def is_available(course, catalog, completed):
    if course not in catalog:
        return False

    prereq_groups = catalog[course]['prerequisites']

    for group in prereq_groups:
        group_satisfied = False

        for prereq in group:
            if prereq in completed:
                group_satisfied = True
                break

            cross_listed = catalog.get(prereq, {}).get('cross_listed', [])
            if any(equiv in completed for equiv in cross_listed):
                group_satisfied = True
                break

        if not group_satisfied:
            return False

    return True