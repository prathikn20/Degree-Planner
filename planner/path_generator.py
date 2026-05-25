from collections import deque
from planner.graph import is_available


def get_prereq_depth(course, catalog, completed_set):
    """BFS to count how many prerequisites deep a course is."""
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

        for or_group in catalog[current]['prerequisites']:
            for prereq in or_group:
                if prereq not in completed_set and prereq not in visited:
                    queue.append((prereq, depth + 1))

    return max_depth


def expand_prerequisites(courses, catalog, completed_set):
    """
    BFS from required courses outward.
    For each OR group, picks the already-satisfied option
    or the shallowest one. Returns full set of courses needed.
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

        for or_group in catalog[course]['prerequisites']:
            # Check if this OR group is already satisfied
            group_satisfied = False
            for option in or_group:
                if option in completed_set or option in all_needed:
                    group_satisfied = True
                    break
                cross_listed = catalog.get(option, {}).get('cross_listed', [])
                if any(eq in completed_set for eq in cross_listed):
                    group_satisfied = True
                    break

            if group_satisfied:
                continue

            # Pick the shallowest option from the OR group
            best = min(
                or_group,
                key=lambda c: get_prereq_depth(c, catalog, completed_set)
            )
            queue.append(best)

    return all_needed


def get_remaining_courses(results, requirements, catalog, completed):
    """
    Reads requirements checker output.
    Returns flat list of courses still needed.
    For choice groups, picks the N shallowest options.
    """
    completed_set = set(completed)
    remaining = []

    program = requirements["CS_major"]

    # Required courses
    for course in program["required_courses"]:
        if course in results["unsatisfied"]:
            remaining.append(course)

    # Choice groups
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

    # Expand to include all transitive prerequisites
    all_needed = expand_prerequisites(required_courses, catalog, completed_set)

    # Filter graph to only relevant courses
    filtered_graph = {
        course: [n for n in neighbors if n in all_needed]
        for course, neighbors in graph.items()
        if course in all_needed
    }

    in_degree = compute_in_degrees(filtered_graph)

    # Seed queue with immediately available courses
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

    # Cycle detection
    if len(result) < len(all_needed):
        unresolved = all_needed - set(result)
        print(f"Warning: unresolvable prerequisites: {unresolved}")

    return result