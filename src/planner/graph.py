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
        for path in data['prerequisites']:
            for prereq in path:
                if prereq in graph:
                    if course not in graph[prereq]:
                        graph[prereq].append(course)
    return graph

def is_available(course, catalog, completed):
    if course not in catalog:
        return False

    pathways = catalog[course]['prerequisites']
    if not pathways:
        return True

    # DNF evaluation: Satisfied if at least one complete tracking branch is valid
    for path in pathways:
        path_satisfied = True
        for prereq in path:
            if prereq in completed:
                continue
            cross_listed = catalog.get(prereq, {}).get('cross_listed', [])
            if any(equiv in completed for equiv in cross_listed):
                continue
            path_satisfied = False
            break
            
        if path_satisfied:
            return True

    return False