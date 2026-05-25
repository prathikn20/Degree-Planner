from collections import deque
from planner.graph import is_available


def compute_in_degrees(graph):
    in_degree = {course: 0 for course in graph}

    for course in graph:
        for neighbor in graph[course]:
            in_degree[neighbor] += 1

    return in_degree


def kahns_algorithm(graph, catalog, completed, required_courses):
    # Only operate on courses not yet completed
    remaining = set(required_courses) - set(completed)

    # Filter graph to only relevant courses
    filtered_graph = {
        course: [n for n in neighbors if n in remaining]
        for course, neighbors in graph.items()
        if course in remaining
    }

    in_degree = compute_in_degrees(filtered_graph)

    # Start queue with all available courses
    queue = deque()
    for course in remaining:
        if in_degree[course] == 0 or is_available(course, catalog, completed):
            queue.append(course)

    result = []
    completed_set = set(completed)

    while queue:
        course = queue.popleft()
        result.append(course)
        completed_set.add(course)

        for neighbor in filtered_graph.get(course, []):
            in_degree[neighbor] -= 1
            if is_available(neighbor, catalog, completed_set):
                queue.append(neighbor)

    # Cycle detection
    if len(result) < len(remaining):
        unresolved = remaining - set(result)
        print(f"Warning: cycle detected or unresolvable prerequisites for: {unresolved}")

    return result