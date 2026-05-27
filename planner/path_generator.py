from collections import deque
from planner.graph import is_available

def get_prereq_depth(course, catalog, completed_set):
    if is_available(course, catalog, completed_set):
        return 0

    visited = set()
    queue = deque([(course, 0)])
    max_depth = 0

    while queue:
        current, depth = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        max_depth = max(max_depth, depth)

        if current not in catalog:
            continue

        for path in catalog[current]['prerequisites']:
            for prereq in path:
                if prereq not in completed_set and prereq not in visited:
                    queue.append((prereq, depth + 1))

    return max_depth

def expand_prerequisites(courses, catalog, completed_set):
    """
    Evaluates tracking options holistically under DNF representation 
    to append minimum required components without track contamination.
    """
    all_needed = set()
    queue = deque(courses)

    while queue:
        course = queue.popleft()
        if course in completed_set or course in all_needed:
            continue

        all_needed.add(course)
        if course not in catalog:
            continue

        pathways = catalog[course]['prerequisites']
        if not pathways:
            continue

        path_satisfied = False
        for path in pathways:
            if all((p in completed_set or p in all_needed) for p in path):
                path_satisfied = True
                break
        if path_satisfied:
            continue

        best_path = min(
            pathways,
            key=lambda path: sum(get_prereq_depth(c, catalog, completed_set) for c in path)
        )
        
        for prereq in best_path:
            queue.append(prereq)

    return all_needed

def get_remaining_courses(results, requirements, catalog, completed):
    completed_set = set(completed)
    remaining = []
    program = requirements["CS_major"]

    for course in program["required_courses"]:
        if course in results["unsatisfied"]:
            remaining.append(course)

    for group in program["choice_groups"]:
        if group["id"] not in results["unsatisfied"]:
            continue

        group_info = results["missing_courses"][group["id"]]
        still_needed = group_info["still_needed"]
        options = group_info["options"]

        sorted_options = sorted(
            options,
            key=lambda c: get_prereq_depth(c, catalog, completed_set)
        )

        chosen = sorted_options[:still_needed]
        remaining.extend(chosen)

    return remaining

def compute_in_degrees(graph):
    in_degree = {course: 0 for course in graph}
    for course in graph:
        for neighbor in graph[course]:
            in_degree[neighbor] += 1
    return in_degree

def kahns_algorithm(graph, catalog, completed, required_courses):
    completed_set = set(completed)
    all_needed = expand_prerequisites(required_courses, catalog, completed_set)

    filtered_graph = {
        course: [n for n in neighbors if n in all_needed]
        for course, neighbors in graph.items()
        if course in all_needed
    }

    in_degree = compute_in_degrees(filtered_graph)
    topo_queue = deque()
    for course in all_needed:
        if is_available(course, catalog, completed_set):
            topo_queue.append(course)

    result = []
    while topo_queue:
        course = topo_queue.popleft()
        result.append(course)
        completed_set.add(course)

        for neighbor in filtered_graph.get(course, []):
            if neighbor not in result and is_available(neighbor, catalog, completed_set):
                topo_queue.append(neighbor)

    if len(result) < len(all_needed):
        unresolved = all_needed - set(result)
        print(f"Warning: unresolvable prerequisites: {unresolved}")

    return result