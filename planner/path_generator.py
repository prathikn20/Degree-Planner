from collections import deque
import heapq
import re
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

        pathways = catalog[current]['prerequisites']
        if not pathways:
            continue

        for path in pathways:
            for prereq in path:
                if prereq not in completed_set and prereq not in visited:
                    queue.append((prereq, depth + 1))

    return max_depth

def expand_prerequisites(courses, catalog, completed_set):
    """
    BFS from required courses outward, evaluating DNF tracks.
    Picks the shallowest entire pathway to avoid hybrid tracks.
    Returns the full set of courses needed.
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

        # Check if an ENTIRE pathway is already satisfied by completed or needed courses
        path_satisfied = False
        for path in pathways:
            components_satisfied = True
            for p in path:
                if p in completed_set or p in all_needed:
                    continue
                cross_listed = catalog.get(p, {}).get('cross_listed', [])
                if any(eq in completed_set or eq in all_needed for eq in cross_listed):
                    continue
                components_satisfied = False
                break
            
            if components_satisfied:
                path_satisfied = True
                break

        if path_satisfied:
            continue

        # If no pathway is satisfied, pick the easiest ENTIRE pathway track
        best_path = min(
            pathways,
            key=lambda path: sum(get_prereq_depth(c, catalog, completed_set) for c in path)
        )
        
        for prereq in best_path:
            queue.append(prereq)

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

    # Expand to include all transitive prerequisites using DNF tracking
    all_needed = expand_prerequisites(required_courses, catalog, completed_set)

    # Filter graph to only relevant courses
    filtered_graph = {
        course: [n for n in neighbors if n in all_needed]
        for course, neighbors in graph.items()
        if course in all_needed
    }

    # Seed queue with a Min-Heap Priority Queue for course-level sorting
    topo_queue = []
    enqueued = set()
    
    for course in all_needed:
        if is_available(course, catalog, completed_set):
            match = re.search(r'\d+', course)
            priority = int(match.group()) if match else 999
            heapq.heappush(topo_queue, (priority, course))
            enqueued.add(course)

    result = []

    while topo_queue:
        priority, course = heapq.heappop(topo_queue)
        result.append(course)
        completed_set.add(course)

        for neighbor in filtered_graph.get(course, []):
            if neighbor not in result and neighbor not in enqueued and is_available(neighbor, catalog, completed_set):
                match = re.search(r'\d+', neighbor)
                n_priority = int(match.group()) if match else 999
                heapq.heappush(topo_queue, (n_priority, neighbor))
                enqueued.add(neighbor)

    # Cycle detection
    if len(result) < len(all_needed):
        unresolved = all_needed - set(result)
        print(f"Warning: unresolved prerequisites: {unresolved}")

    return result