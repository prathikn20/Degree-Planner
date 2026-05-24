import json
from collections import deque

def load_catalog(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)

def load_requirements(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)

def build_graph(catalog):
    # Initialize every course with an empty forward-edge list
    graph = {course: [] for course in catalog}
    
    for course, data in catalog.items():
        # Each prereq_group is one AND requirement — a list of OR options
        for prereq_group in data['prerequisites']:
            for prereq in prereq_group:
                # prereq unlocks course — add forward edge
                if prereq in graph:
                    if course not in graph[prereq]:
                        graph[prereq].append(course)
    
    return graph

def is_available(course, catalog, completed):
    if course not in catalog:
        return False
    
    prereq_groups = catalog[course]['prerequisites']
    
    # Every group must be satisfied (AND logic)
    for group in prereq_groups:
        # Build expanded set including cross-listed equivalents
        group_satisfied = False
        
        for prereq in group:
            # Check if prereq itself is completed
            if prereq in completed:
                group_satisfied = True
                break
            
            # Check cross-listed equivalents
            cross_listed = catalog.get(prereq, {}).get('cross_listed', [])
            if any(equiv in completed for equiv in cross_listed):
                group_satisfied = True
                break
        
        # If any AND group is unsatisfied, course is unavailable
        if not group_satisfied:
            return False
    
    return True
